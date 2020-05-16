# ovirt-imageio
# Copyright (C) 2015-2016 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from __future__ import absolute_import

import logging

from . import errors
from . import stats

log = logging.getLogger("ops")


class EOF(Exception):
    """ Raised when no more data is available and size was not specifed """


class Operation(object):

    def __init__(self, size=None, offset=0, buf=None, clock=stats.NullClock()):
        self._size = size
        self._offset = offset
        self._buf = buf
        self._done = 0
        self._clock = clock

    @property
    def size(self):
        return self._size

    @property
    def offset(self):
        return self._offset

    @property
    def done(self):
        return self._done

    @property
    def _todo(self):
        if self._size is None:
            return len(self._buf) if self._buf else 1024**2
        return self._size - self._done

    def run(self):
        with self._clock.run("operation"):
            self._run()

    def __repr__(self):
        return ("<{self.__class__.__name__} "
                "size={self.size} "
                "offset={self._offset} "
                "done={self.done} "
                "at 0x{id}>").format(self=self, id=id(self))


class Send(Operation):
    """
    Send data source backend to file object.
    """

    def __init__(self, src, dst, buf, size=None, offset=0,
                 clock=stats.NullClock()):
        super(Send, self).__init__(size=size, offset=offset, buf=buf,
                                   clock=clock)
        self._src = src
        self._dst = dst

    def _run(self):
        try:
            skip = self._offset % self._src.block_size
            self._src.seek(self._offset - skip)
            if skip:
                self._send_chunk(self._buf, skip)
            while self._todo:
                self._send_chunk(self._buf)
        except EOF:
            pass

    def _send_chunk(self, buf, skip=0):
        if self._src.tell() % self._src.block_size:
            if self._size is None:
                raise EOF
            raise errors.PartialContent(self.size, self.done)

        with self._clock.run("read") as s:
            count = self._src.readinto(buf)
            s.bytes += count
        if count == 0:
            if self._size is None:
                raise EOF
            raise errors.PartialContent(self.size, self.done)

        size = min(count - skip, self._todo)
        with memoryview(buf)[skip:skip + size] as view:
            with self._clock.run("write") as s:
                self._dst.write(view)
                s.bytes += size
        self._done += size


class Receive(Operation):
    """
    Receive data from file object to destination backend.
    """

    def __init__(self, dst, src, buf, size=None, offset=0, flush=True,
                 clock=stats.NullClock()):
        super(Receive, self).__init__(size=size, offset=offset, buf=buf,
                                      clock=clock)
        self._src = src
        self._dst = dst
        self._flush = flush

    def _run(self):
        try:
            self._dst.seek(self._offset)

            # If offset is not aligned to block size, receive partial chunk
            # until the start of the next block.
            unaligned = self._offset % self._dst.block_size
            if unaligned:
                count = min(self._todo, self._dst.block_size - unaligned)
                self._receive_chunk(self._buf, count)

            # Now current file position is aligned to block size and we can
            # receive full chunks.
            while self._todo:
                count = min(self._todo, len(self._buf))
                self._receive_chunk(self._buf, count)
        except EOF:
            pass

        if self._flush:
            with self._clock.run("sync"):
                self._dst.flush()

    def _receive_chunk(self, buf, count):
        buf.seek(0)
        with memoryview(buf)[:count] as view:
            read = 0
            while read < count:
                with view[read:] as v:
                    with self._clock.run("read") as s:
                        n = self._src.readinto(v)
                        s.bytes += n
                if not n:
                    break
                read += n

            pos = 0
            while pos < read:
                with view[pos:read] as v:
                    with self._clock.run("write") as s:
                        n = self._dst.write(v)
                        s.bytes += n
                pos += n

        self._done += read
        if read < count:
            if self._size is None:
                raise EOF
            raise errors.PartialContent(self.size, self.done)


class Zero(Operation):
    """
    Zero byte range.
    """

    # Limit zero size so we update self._done frequently enough to provide
    # progress even with slow storage.
    MAX_STEP = 1024**3

    def __init__(self, dst, size, offset=0, flush=False,
                 clock=stats.NullClock()):
        super(Zero, self).__init__(size=size, offset=offset, clock=clock)
        self._dst = dst
        self._flush = flush

    def _run(self):
        self._dst.seek(self._offset)

        while self._todo:
            step = min(self._todo, self.MAX_STEP)
            with self._clock.run("zero") as s:
                n = self._dst.zero(step)
                s.bytes += n
            self._done += n

        if self._flush:
            self.flush()

    def flush(self):
        with self._clock.run("flush"):
            self._dst.flush()


class Flush(Operation):
    """
    Flush received data to storage.
    """

    def __init__(self, dst, clock=stats.NullClock()):
        super(Flush, self).__init__(clock=clock)
        self._dst = dst

    def _run(self):
        with self._clock.run("flush"):
            self._dst.flush()

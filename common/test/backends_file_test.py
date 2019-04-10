# ovirt-imageio
# Copyright (C) 2015-2018 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from __future__ import absolute_import

import errno
import io
import os

from contextlib import closing

from six.moves import urllib_parse

import pytest

from ovirt_imageio_common import util
from ovirt_imageio_common.backends import file


def test_debugging_interface(tmpurl):
    with file.open(tmpurl, "r+") as f:
        assert f.readable()
        assert f.writable()
        assert not f.sparse
        assert f.name == "file"


def test_open_write_only(tmpurl):
    with file.open(tmpurl, "w") as f, \
            closing(util.aligned_buffer(512)) as buf:
        assert not f.readable()
        assert f.writable()
        buf.write(b"x" * 512)
        f.write(buf)
    with io.open(tmpurl.path, "rb") as f:
        assert f.read() == b"x" * 512


def test_open_write_only_truncate(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 512)
    with file.open(tmpurl, "w") as f:
        pass
    with io.open(tmpurl.path, "rb") as f:
        assert f.read() == b""


def test_open_read_only(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 512)
    with file.open(tmpurl, "r") as f, \
            closing(util.aligned_buffer(512)) as buf:
        assert f.readable()
        assert not f.writable()
        f.readinto(buf)
        assert buf[:] == b"x" * 512


def test_open_read_write(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"a" * 512)
    with file.open(tmpurl, "r+") as f, \
            closing(util.aligned_buffer(512)) as buf:
        assert f.readable()
        assert f.writable()
        f.readinto(buf)
        buf[:] = b"b" * 512
        f.seek(0)
        f.write(buf)
    with io.open(tmpurl.path, "rb") as f:
        assert f.read() == b"b" * 512


@pytest.mark.parametrize("mode", ["r", "r+"])
def test_open_no_create(mode):
    with pytest.raises(OSError) as e:
        missing = urllib_parse.urlparse("file:/no/such/path")
        with file.open(missing, mode):
            pass
    assert e.value.errno == errno.ENOENT


def test_block_size(tmpurl):
    with file.open(tmpurl, "r") as f:
        # We don't support yet 4k drives.
        assert f.block_size == 512


def test_readinto(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"a" * 4096)
    with file.open(tmpurl, "r") as f, \
            closing(util.aligned_buffer(4096)) as buf:
        n = f.readinto(buf)
        assert n == len(buf)
        assert f.tell() == len(buf)
        assert buf[:] == b"a" * 4096


def test_readinto_short_ulinged(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"a" * 4096)
    with file.open(tmpurl, "r") as f, \
            closing(util.aligned_buffer(8192)) as buf:
        n = f.readinto(buf)
        assert n == 4096
        assert f.tell() == 4096
        assert buf[:4096] == b"a" * 4096
        assert buf[4096:] == b"\0" * 4096


def test_readinto_short_unaligned(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"a" * 42)
    with file.open(tmpurl, "r") as f, \
            closing(util.aligned_buffer(4096)) as buf:
        n = f.readinto(buf)
        assert n == 42
        assert f.tell() == 42
        assert buf[:42] == b"a" * 42
        assert buf[42:] == b"\0" * (4096 - 42)


def test_write_aligned_middle(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"a" * 4 * 4096)
    with file.open(tmpurl, "r+") as f, \
            closing(util.aligned_buffer(8192)) as buf:
        buf.write(b"b" * 8192)
        f.seek(4096)
        n = f.write(buf)
        assert n == len(buf)
        assert f.tell() == 4096 + len(buf)
    with io.open(tmpurl.path, "rb") as f:
        assert f.read(4096) == b"a" * 4096
        assert f.read(8192) == b"b" * 8192
        assert f.read() == b"a" * 4096


def test_write_aligned_at_end(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"a" * 8192)
    with file.open(tmpurl, "r+") as f, \
            closing(util.aligned_buffer(8192)) as buf:
        buf.write(b"b" * 8192)
        f.seek(4096)
        n = f.write(buf)
        assert n == len(buf)
        assert f.tell() == 4096 + len(buf)
    with io.open(tmpurl.path, "rb") as f:
        assert f.read(4096) == b"a" * 4096
        assert f.read() == b"b" * 8192


def test_write_aligned_after_end(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"a" * 4096)
    with file.open(tmpurl, "r+") as f, \
            closing(util.aligned_buffer(8192)) as buf:
        buf.write(b"b" * 8192)
        f.seek(8192)
        n = f.write(buf)
        assert n == len(buf)
        assert f.tell() == 8192 + len(buf)
    with io.open(tmpurl.path, "rb") as f:
        assert f.read(4096) == b"a" * 4096
        assert f.read(4096) == b"\0" * 4096
        assert f.read() == b"b" * 8192


def test_write_unaligned_offset_complete(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 1024)

    # Write 10 bytes into the second block.
    with file.open(tmpurl, "r+") as f:
        f.seek(600)
        n = f.write(b"y" * 10)
        assert n == 10
        assert f.tell() == 610

    with io.open(tmpurl.path, "rb") as f:
        assert f.read(600) == b"x" * 600
        assert f.read(10) == b"y" * 10
        assert f.read() == b"x" * (1024 - 610)


def test_write_unaligned_offset_inside(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 1024)

    # Write 12 bytes into the first block.
    with file.open(tmpurl, "r+") as f:
        f.seek(500)
        n = f.write(b"y" * 100)
        assert n == 12
        assert f.tell() == 512

    with io.open(tmpurl.path, "rb") as f:
        assert f.read(500) == b"x" * 500
        assert f.read(12) == b"y" * 12
        assert f.read() == b"x" * 512


def test_write_unaligned_offset_at_end(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 1024)

    # Write 24 bytes into the last block.
    with file.open(tmpurl, "r+") as f:
        f.seek(1000)
        n = f.write(b"y" * 100)
        assert n == 24
        assert f.tell() == 1024

    with io.open(tmpurl.path, "rb") as f:
        assert f.read(1000) == b"x" * 1000
        assert f.read() == b"y" * 24


def test_write_unaligned_offset_after_end(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 512)

    with file.open(tmpurl, "r+") as f:
        f.seek(600)
        n = f.write(b"y" * 10)
        assert n == 10
        assert f.tell() == 610

    with io.open(tmpurl.path, "rb") as f:
        assert f.read(512) == b"x" * 512
        assert f.read(88) == b"\0" * 88
        assert f.read(10) == b"y" * 10
        assert f.read() == b"\0" * (1024 - 610)


def test_write_unaligned_buffer_slow_path(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 1024)

    # Perform slow read-modify-write in the second block.
    with file.open(tmpurl, "r+") as f:
        f.seek(512)
        n = f.write(b"y" * 10)
        assert n == 10
        assert f.tell() == 522

    with io.open(tmpurl.path, "rb") as f:
        assert f.read(512) == b"x" * 512
        assert f.read(10) == b"y" * 10
        assert f.read() == b"x" * (1024 - 522)


def test_write_unaligned_buffer_fast_path(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 4096)

    # Perform short fast write of 6 blocks.
    buf = util.aligned_buffer(3073)
    buf.write(b"y" * 3073)
    with closing(buf):
        with file.open(tmpurl, "r+") as f:
            f.seek(512)
            n = f.write(buf)
            assert n == 3072
            assert f.tell() == 3584

    with io.open(tmpurl.path, "rb") as f:
        assert f.read(512) == b"x" * 512
        assert f.read(3072) == b"y" * 3072
        assert f.read() == b"x" * 512


def test_flush(tmpurl, monkeypatch):
    count = [0]

    def fsync(fd):
        count[0] += 1

    # This is ugly but probably the only way to test that we call fsync.
    monkeypatch.setattr(os, "fsync", fsync)
    with file.open(tmpurl, "r+") as f:
        f.write(b"x")
        f.flush()
    assert count[0] == 1


@pytest.mark.parametrize("sparse", [True, False])
def test_zero_aligned_middle(tmpurl, sparse):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 3 * 4096)
    with file.open(tmpurl, "r+", sparse=sparse) as f:
        f.seek(4096)
        n = f.zero(4096)
        assert n == 4096
        assert f.tell() == 8192
    with io.open(tmpurl.path, "rb") as f:
        assert f.read(4096) == b"x" * 4096
        assert f.read(4096) == b"\0" * 4096
        assert f.read() == b"x" * 4096


@pytest.mark.parametrize("sparse", [True, False])
def test_zero_aligned_at_end(tmpurl, sparse):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 4096)
    with file.open(tmpurl, "r+", sparse=sparse) as f:
        assert f.sparse == sparse
        f.seek(4096)
        n = f.zero(4096)
        assert n == 4096
        assert f.tell() == 8192
    with io.open(tmpurl.path, "rb") as f:
        assert f.read(4096) == b"x" * 4096
        assert f.read() == b"\0" * 4096


@pytest.mark.parametrize("sparse", [True, False])
def test_zero_aligned_after_end(tmpurl, sparse):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 4096)
    with file.open(tmpurl, "r+", sparse=sparse) as f:
        f.seek(8192)
        n = f.zero(4096)
        assert n == 4096
        assert f.tell() == 12288
    with io.open(tmpurl.path, "rb") as f:
        assert f.read(4096) == b"x" * 4096
        assert f.read() == b"\0" * 8192


def test_zero_allocate_space(tmpurl):
    with file.open(tmpurl, "r+", sparse=False) as f:
        f.zero(8192)
    # File system may report more than file size.
    assert os.stat(tmpurl.path).st_blocks * 512 >= 8192


def test_zero_sparse_deallocate_space(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 8192)
    with file.open(tmpurl, "r+", sparse=True) as f:
        f.zero(8192)
    assert os.stat(tmpurl.path).st_blocks * 512 < 8192


def test_zero_unaligned_offset_complete(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 1024)

    # Zero 10 bytes into the second block.
    with file.open(tmpurl, "r+") as f:
        f.seek(600)
        n = f.zero(10)
        assert n == 10
        assert f.tell() == 610

    with io.open(tmpurl.path, "rb") as f:
        assert f.read(600) == b"x" * 600
        assert f.read(10) == b"\0" * 10
        assert f.read() == b"x" * (1024 - 610)


def test_zero_unaligned_offset_inside(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 1024)

    # Zero 12 bytes into the first block.
    with file.open(tmpurl, "r+") as f:
        f.seek(500)
        n = f.zero(100)
        assert n == 12
        assert f.tell() == 512

    with io.open(tmpurl.path, "rb") as f:
        assert f.read(500) == b"x" * 500
        assert f.read(12) == b"\0" * 12
        assert f.read() == b"x" * 512


def test_zero_unaligned_offset_at_end(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 1024)

    # Zero 24 bytes into the last block.
    with file.open(tmpurl, "r+") as f:
        f.seek(1000)
        n = f.zero(100)
        assert n == 24
        assert f.tell() == 1024

    with io.open(tmpurl.path, "rb") as f:
        assert f.read(1000) == b"x" * 1000
        assert f.read() == b"\0" * 24


def test_zero_unaligned_offset_after_end(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 512)

    with file.open(tmpurl, "r+") as f:
        f.seek(600)
        n = f.zero(10)
        assert n == 10
        assert f.tell() == 610

    with io.open(tmpurl.path, "rb") as f:
        assert f.read(512) == b"x" * 512
        assert f.read() == b"\0" * 512


def test_zero_unaligned_buffer_slow_path(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 1024)

    # Perform slow read-modify-write in the second block.
    with file.open(tmpurl, "r+") as f:
        f.seek(512)
        n = f.zero(10)
        assert n == 10
        assert f.tell() == 522

    with io.open(tmpurl.path, "rb") as f:
        assert f.read(512) == b"x" * 512
        assert f.read(10) == b"\0" * 10
        assert f.read() == b"x" * 502


def test_zero_unaligned_buffer_fast_path(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.write(b"x" * 4096)

    # Perform fast short zero of 6 blocks.
    with file.open(tmpurl, "r+") as f:
        f.seek(512)
        n = f.zero(3073)
        assert n == 3072
        assert f.tell() == 3584

    with io.open(tmpurl.path, "rb") as f:
        assert f.read(512) == b"x" * 512
        assert f.read(3072) == b"\0" * 3072
        assert f.read() == b"x" * 512


def test_dirty(tmpurl):
    # backend created clean
    m = file.open(tmpurl, "r+")
    assert not m.dirty

    buf = util.aligned_buffer(4096)
    with closing(buf):
        # write ans zero dirty the backend
        buf.write(b"x" * 4096)
        m.write(buf)
        assert m.dirty
        m.flush()
        assert not m.dirty
        m.zero(4096)
        assert m.dirty
        m.flush()
        assert not m.dirty

        # readinto, seek do not affect dirty.
        m.seek(0)
        assert not m.dirty
        m.readinto(buf)
        assert not m.dirty


def test_size(tmpurl):
    with io.open(tmpurl.path, "wb") as f:
        f.truncate(1024)
    with file.open(tmpurl, "r+") as f:
        assert f.size() == 1024
        assert f.tell() == 0
        f.zero(2048)
        f.seek(100)
        assert f.size() == 2048
        assert f.tell() == 100

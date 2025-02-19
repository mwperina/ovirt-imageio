// ovirt-imageio
// Copyright (C) 2021 Red Hat, Inc.
//
// This program is free software; you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation; either version 2 of the License, or
// (at your option) any later version.

package qemuimg

import (
	"encoding/json"
	"fmt"
	"os/exec"
)

type ImageInfo struct {
	Format string `json:"format"`
	Size   uint64 `json:"virtual-size"`
}

func Info(filename string) (*ImageInfo, error) {
	out, err := run("qemu-img", "info", "--output", "json", filename)
	if err != nil {
		return nil, err
	}

	var info ImageInfo
	if err = json.Unmarshal(out, &info); err != nil {
		return nil, err
	}

	return &info, nil
}

func run(name string, arg ...string) ([]byte, error) {
	cmd := exec.Command(name, arg...)

	stdout, err := cmd.Output()

	if err != nil {
		var stderr []byte
		if ee, ok := err.(*exec.ExitError); ok {
			stderr = ee.Stderr
		}
		return stdout, fmt.Errorf(
			"Command %v failed rc=%v: out=%q err=%q",
			cmd.Args,
			cmd.ProcessState.ExitCode(),
			stdout,
			stderr,
		)
	}

	return stdout, nil
}

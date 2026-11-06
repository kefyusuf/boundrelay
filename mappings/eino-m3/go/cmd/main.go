// Command main is the boundrelay-m3-eino CLI entry point: the P5d mapping's
// executable boundary mirroring the Go M3 runtime's cmd wiring.
package main

import (
	"os"

	"boundrelay-m3-eino/internal/cli"
)

func main() {
	os.Exit(cli.RunCLI(os.Args[1:], os.Stdout, os.Stderr))
}

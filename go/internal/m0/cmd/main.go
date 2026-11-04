// Command cmd runs one support-triage case through the Go M0 runtime,
// mirroring the TS/Python CLI grammar (--mode/--case/--trace).
package main

import (
	"os"

	"github.com/kefyusuf/boundrelay/go/internal/m0"
)

func main() {
	os.Exit(m0.RunCLI(os.Args[1:], os.Stdout, os.Stderr))
}

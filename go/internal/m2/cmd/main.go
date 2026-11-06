// Command cmd runs one support-handoff case through the Go M2 runtime,
// mirroring the TS/Python CLI grammar (--mode/--case/--trace).
package main

import (
	"os"

	"github.com/kefyusuf/boundrelay/go/internal/m2"
)

func main() {
	os.Exit(m2.RunCLI(os.Args[1:], os.Stdout, os.Stderr))
}

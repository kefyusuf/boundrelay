// Command cmd runs one order-brief-recovery lifecycle through the Go M4
// runtime, mirroring the TS/Python CLI grammar
// (--case/--trace/--state-dir [--resume] [--replay-from]).
package main

import (
	"os"

	"github.com/kefyusuf/boundrelay/go/internal/m4"
)

func main() {
	os.Exit(m4.RunCLI(os.Args[1:], os.Stdout, os.Stderr))
}

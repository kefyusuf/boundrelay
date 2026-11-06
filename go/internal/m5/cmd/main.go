// Command cmd runs one order-closure lifecycle through the Go M5 runtime,
// mirroring the TS/Python CLI grammar (--case/--trace/--state-dir
// [--resume]).
package main

import (
	"os"

	"github.com/kefyusuf/boundrelay/go/internal/m5"
)

func main() {
	os.Exit(m5.RunCLI(os.Args[1:], os.Stdout, os.Stderr))
}

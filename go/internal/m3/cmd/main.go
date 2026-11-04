// Command cmd runs one order-brief case through the Go M3 runtime,
// mirroring the TS/Python CLI grammar (--mode/--case/--trace).
package main

import (
	"os"

	"github.com/kefyusuf/boundrelay/go/internal/m3"
)

func main() {
	os.Exit(m3.RunCLI(os.Args[1:], os.Stdout, os.Stderr))
}

// Command cmd runs one order-investigation case through the Go M1 runtime,
// mirroring the TS/Python CLI grammar (--mode/--case/--trace).
package main

import (
	"os"

	"github.com/kefyusuf/boundrelay/go/internal/m1"
)

func main() {
	os.Exit(m1.RunCLI(os.Args[1:], os.Stdout, os.Stderr))
}

package m2

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"
)

// CLI option names mirroring the TS/Python M2 grammar exactly.
const (
	optionMode  = "--mode"
	optionCase  = "--case"
	optionTrace = "--trace"
)

// CLIOptions is the parsed command line.
type CLIOptions struct {
	Mode      string
	CaseID    string
	TracePath string
}

// ParseCLIOptions parses the M2 CLI grammar: exactly one value per option,
// no unknown or duplicate options, no missing values, all three options
// present, and a bounded router mode.
func ParseCLIOptions(args []string) (CLIOptions, error) {
	values := map[string]string{}
	for index := 0; index < len(args); index += 2 {
		name := args[index]
		if name != optionMode && name != optionCase && name != optionTrace {
			return CLIOptions{}, fmt.Errorf("unexpected argument %q", name)
		}
		if _, duplicate := values[name]; duplicate {
			return CLIOptions{}, fmt.Errorf("duplicate option %s", name)
		}
		if index+1 >= len(args) || strings.HasPrefix(args[index+1], "--") {
			return CLIOptions{}, fmt.Errorf("missing required option %s", name)
		}
		values[name] = args[index+1]
	}
	for _, name := range []string{optionMode, optionCase, optionTrace} {
		if _, ok := values[name]; !ok {
			return CLIOptions{}, fmt.Errorf("missing required option %s", name)
		}
	}
	mode := values[optionMode]
	if mode != ModeCode && mode != ModeModel {
		return CLIOptions{}, fmt.Errorf("--mode must be code or model")
	}
	return CLIOptions{Mode: mode, CaseID: values[optionCase], TracePath: values[optionTrace]}, nil
}

// RunCLI is the CLI boundary: one nonblank JSON result line on stdout with
// exit 0 for domain outcomes (including FAILED results), exit 2 with a
// stderr diagnostic for tooling errors.
func RunCLI(args []string, stdout io.Writer, stderr io.Writer) int {
	options, err := ParseCLIOptions(args)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	report, err := RunCase(RunOptions{
		Mode: options.Mode, CaseID: options.CaseID, TracePath: options.TracePath})
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	line, err := json.Marshal(report.Result)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	fmt.Fprintf(stdout, "%s\n", line)
	return 0
}

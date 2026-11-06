// Package cli is the mapping's command boundary: --case <id> [--mode
// corrected|naive] --trace <file>. Exactly one JSON result line on stdout,
// exit 0 for every domain result (SUCCEEDED, PARTIAL, FAILED); tooling
// failures - unknown or missing options, unknown case, naive-mode default
// propagation - print a stderr diagnostic and exit 2 without a canonical
// result.
package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"boundrelay-m3-eino/internal/mapping"
)

// CLIOptions is the parsed command line.
type CLIOptions struct {
	Mode      string // corrected (default) | naive
	CaseID    string
	TracePath string
}

const (
	optionMode  = "--mode"
	optionCase  = "--case"
	optionTrace = "--trace"

	defaultMode = "corrected"
)

// ParseCLIOptions parses the mapping CLI grammar: exactly one value per
// option, no unknown or duplicate options, no missing values, --case and
// --trace required, --mode optional with a bounded value.
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
			return CLIOptions{}, fmt.Errorf("missing required value for %s", name)
		}
		values[name] = args[index+1]
	}
	caseID, ok := values[optionCase]
	if !ok {
		return CLIOptions{}, fmt.Errorf("missing required option %s", optionCase)
	}
	tracePath, ok := values[optionTrace]
	if !ok {
		return CLIOptions{}, fmt.Errorf("missing required option %s", optionTrace)
	}
	mode, ok := values[optionMode]
	if !ok {
		mode = defaultMode
	}
	if mode != "corrected" && mode != "naive" {
		return CLIOptions{}, fmt.Errorf("--mode must be corrected or naive")
	}
	return CLIOptions{Mode: mode, CaseID: caseID, TracePath: tracePath}, nil
}

// RunCLI is the CLI boundary: one nonblank JSON result line on stdout with
// exit 0 for domain outcomes (including PARTIAL/FAILED results), exit 2
// with a stderr diagnostic for tooling errors.
func RunCLI(args []string, stdout io.Writer, stderr io.Writer) int {
	options, err := ParseCLIOptions(args)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	if options.Mode == "naive" {
		report, err := mapping.RunNaive(context.Background(), mapping.NaiveOptions{
			CaseID: options.CaseID, TracePath: options.TracePath})
		if err != nil {
			fmt.Fprintln(stderr, err)
			return 2
		}
		return printResult(report, stdout, stderr)
	}
	report, err := mapping.RunCase(context.Background(), mapping.RunOptions{
		CaseID: options.CaseID, TracePath: options.TracePath})
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	return printResult(report, stdout, stderr)
}

func printResult(report mapping.RunReport, stdout io.Writer, stderr io.Writer) int {
	line, err := json.Marshal(report.Result)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	fmt.Fprintf(stdout, "%s\n", line)
	return 0
}

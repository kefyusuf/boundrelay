package m4

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
)

// CLI option names mirroring the TS/Python M4 grammar exactly: three value
// options, one value option for the replay anchor, and the --resume flag.
const (
	optionCase       = "--case"
	optionTrace      = "--trace"
	optionStateDir   = "--state-dir"
	optionReplayFrom = "--replay-from"
	optionResume     = "--resume"
)

// CLIOptions is the parsed command line.
type CLIOptions struct {
	CaseID     string
	TracePath  string
	StateDir   string
	ReplayFrom string
	Resume     bool
}

// ParseCLIOptions parses the M4 CLI grammar: exactly one value per option,
// no unknown or duplicate options, no missing values, all three required
// options present, and resume/replay mutually exclusive.
func ParseCLIOptions(args []string) (CLIOptions, error) {
	values := map[string]string{}
	flags := map[string]bool{}
	parsed := CLIOptions{}
	for index := 0; index < len(args); index++ {
		name := args[index]
		if name != optionCase && name != optionTrace && name != optionStateDir &&
			name != optionReplayFrom && name != optionResume {
			return CLIOptions{}, fmt.Errorf("unexpected argument %q", name)
		}
		if name == optionResume {
			if flags[optionResume] {
				return CLIOptions{}, fmt.Errorf("duplicate option %s", name)
			}
			flags[name] = true
			continue
		}
		if _, duplicate := values[name]; duplicate {
			return CLIOptions{}, fmt.Errorf("duplicate option %s", name)
		}
		if index+1 >= len(args) || strings.HasPrefix(args[index+1], "--") {
			return CLIOptions{}, fmt.Errorf("missing required option %s", name)
		}
		values[name] = args[index+1]
		index++
	}
	for _, name := range []string{optionCase, optionTrace, optionStateDir} {
		if _, ok := values[name]; !ok {
			return CLIOptions{}, fmt.Errorf("missing required option %s", name)
		}
	}
	if flags[optionResume] {
		if _, replay := values[optionReplayFrom]; replay {
			return CLIOptions{}, fmt.Errorf("resume and replay are mutually exclusive")
		}
	}
	parsed = CLIOptions{CaseID: values[optionCase], TracePath: values[optionTrace],
		StateDir: values[optionStateDir], ReplayFrom: values[optionReplayFrom],
		Resume: flags[optionResume]}
	return parsed, nil
}

// RunCLI is the CLI boundary: one nonblank JSON result line on stdout with
// exit 0 for domain outcomes (including CANCELLED and FAILED results), exit
// 2 with a stderr diagnostic for tooling errors. The crash control exits 2
// from inside the run after flushing the trace prefix, printing nothing.
func RunCLI(args []string, stdout io.Writer, stderr io.Writer) int {
	options, err := ParseCLIOptions(args)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	report, err := RunCase(context.Background(), RunOptions{
		CaseID: options.CaseID, TracePath: options.TracePath,
		StateDir: options.StateDir, Resume: options.Resume,
		ReplayFrom: options.ReplayFrom})
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

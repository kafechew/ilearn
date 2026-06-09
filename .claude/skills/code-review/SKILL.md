# Code Review

Run a comprehensive code review using parallel agents, then synthesize findings.

## Scope

Determine what code to review using this priority:

1. User specifies scope - If the user provides a branch name, commit SHA, PR number/URL, or file paths, review that
2. On a feature branch - Review all changes on current branch vs main/master (git diff main...HEAD)
3. On main/master with staged changes - Review staged files (git diff --staged)
4. On main/master, nothing staged - Review the latest commit (git show HEAD)

## Preset Modes

If the user passes a mode flag, only launch the agents listed for that mode. If no flag is given, default to --full.

| Mode     | Agents                                          | When to use                                  |
|----------|-------------------------------------------------|----------------------------------------------|
| --full   | All 9 agents                                    | Default — thorough review before merging     |
| --quick  | Tests, Linter, Security                         | Fast check during active development         |
| --security | Security only                                 | After touching auth, permissions, user input |
| --perf   | Performance only                                | After touching queries, loops, large datasets|
| --quality| Code Reviewer, Quality & Style, Simplification  | Before a PR — focus on code quality          |
| --deploy | Dependency & Deployment Safety, Linter, Tests   | Before deploying — migration and safety check|
| --tests  | Test Runner, Test Quality Reviewer              | After writing or changing tests              |

## Instructions

Launch all relevant agents in parallel using a single message with multiple Task tool calls:

### Agent 1: Test Runner
Run relevant tests for the changed files. Report:
- Which tests were run
- Pass/fail status
- Any test failures with details

### Agent 2: Linter & Static Analysis
Run linters AND collect IDE diagnostics for the changed files. Report:
- Linting tool(s) used
- Any warnings or errors found
- Auto-fixable vs manual fixes needed
- Type errors or unresolved references

### Agent 3: Code Reviewer
First, check if CLAUDE.md exists and read it for project conventions.
Provide up to 5 concrete improvements ranked by impact and effort.
Format each as:
[HIGH/MED/LOW Impact, HIGH/MED/LOW Effort] Title
- What: Description
- Why: Why it matters
- How: Concrete fix
Focus on non-obvious improvements. Skip formatting and things linters catch.

### Agent 4: Security Reviewer
Check for:
- Input validation and sanitization
- Injection risks (SQL, command, XSS)
- Authentication/authorization issues
- Secrets or credentials in code
- Error handling that leaks sensitive info
Report with severity (Critical/High/Medium/Low) and file:line references.
If clean: "No security concerns identified."

### Agent 5: Quality & Style Reviewer
First, check if CLAUDE.md exists and read it for project conventions.
Check for complexity, dead code, duplication, naming conventions, file organization, architectural patterns, and consistency with surrounding code.
If clean: "No quality or style issues identified."

### Agent 6: Test Quality Reviewer
Evaluate coverage ROI, behavior vs implementation testing, flakiness risks, and anti-patterns (over-mocking, testing internals, coverage for coverage sake).
If balanced: "Test coverage is appropriate and behavior-focused."

### Agent 7: Performance Reviewer
Check for:
- N+1 queries or inefficient data fetching
- Blocking operations in async contexts
- Memory leaks
- Missing pagination for large datasets
- Expensive operations in hot paths
If clean: "No performance concerns identified."

### Agent 8: Dependency, Breaking Changes & Deployment Safety Reviewer
Check new dependencies (justified? maintained?), breaking changes, migration safety, deployment ordering, rollback safety, and observability.
If clean: "No dependency, compatibility, or deployment concerns."

### Agent 9: Simplification & Maintainability Reviewer
Ask "could this be simpler?" Check for premature abstractions, over-engineering, and whether the change is atomic and well-scoped.
If clean: "Code complexity is proportionate to the problem and changes are well-scoped."

## After Agents Complete: Synthesize Results

Produce a prioritized summary using this format:

╔══════════════════════════════════════════════════════════════╗
║                     CODE REVIEW SUMMARY                      ║
║  Branch: {branch}    Files changed: {N}    {date}            ║
╚══════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴  CRITICAL  (must fix before merge)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Category]  Issue title
  → path/to/file.php:line
  → One line explanation

[Only show severity blocks that have findings — omit empty ones]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅  ALL CLEAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Tests        N passed, 0 failed
  Linter       No issues
  [other clean agents...]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  VERDICT:  ✅ READY TO MERGE
            OR ⚠️  NEEDS ATTENTION — X medium issues to address
            OR ❌  NEEDS WORK — X critical/high issues must be fixed

  {One sentence on what to do next}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Verdict guidelines:
- READY TO MERGE: All tests pass, no critical/high issues
- NEEDS ATTENTION: Medium issues or important suggestions
- NEEDS WORK: Critical/high issues or failing tests
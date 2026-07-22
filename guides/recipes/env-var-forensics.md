# Recipe: Env Var Forensics

> When an environment variable has a mysterious value, hunt it through every layer — don't guess.

## When to use

- A variable has a value you didn't set explicitly (e.g., `CLAUDE_CODE_EFFORT_LEVEL=high` when you never wrote that)
- A child process sees different env than your shell
- A setting persists across restarts with no obvious source
- You need to explain where a value came from before changing it

## The recipe — layered checklist

Walk every layer in order. **Report each layer even if empty.** Gaps reveal themselves.

**1. Current process env**

```bash
ps -E -p $$                  # macOS
cat /proc/self/environ | tr '\0' '\n'  # Linux
env | grep VAR_NAME
```

**2. launchctl (macOS GUI apps inherit from here)**

```bash
launchctl getenv VAR_NAME
launchctl print gui/$(id -u) | grep VAR_NAME
```

**3. Shell rc files**

Check all of these, in order:

```bash
~/.zshenv ~/.zprofile ~/.zshrc ~/.zlogin
~/.bash_profile ~/.bashrc ~/.profile
/etc/zshenv /etc/zprofile /etc/profile
```

Grep for both `export VAR=` and `VAR=` (function-local).

**4. Claude settings**

```bash
~/.claude/settings.json
~/.claude/settings.local.json
<project>/.claude/settings.json
<project>/.claude/settings.local.json
```

Look for `"env": { "VAR_NAME": ... }`.

**5. Shell functions and aliases**

```bash
type VAR_NAME
which -a <command-that-sets-it>
alias | grep VAR_NAME
```

**6. Wrapper scripts in PATH**

```bash
echo $PATH | tr ':' '\n'
# For each entry, check if a wrapper sets the var:
for dir in $(echo $PATH | tr ':' '\n'); do grep -l VAR_NAME "$dir"/* 2>/dev/null; done
```

## Failure modes

Without this recipe:

- Agent guesses "maybe it's in `.zshrc`" without checking, user confirms it isn't, another 10 min lost
- Variable is actually set by a wrapper script in `PATH` that shadows the real binary — never discovered
- launchctl value overrides shell value in GUI-launched apps but the agent only checks shell
- A user spends an evening hunting for where `CLAUDE_CODE_EFFORT_LEVEL=high` was set (the original /insights finding that motivated this recipe)

## Example — copy-pasteable hunt prompt

```
Hunt where VAR_NAME is set. Walk all 6 layers and report each:
1. `ps -E -p $$` and `env | grep VAR_NAME`
2. `launchctl getenv VAR_NAME`
3. Grep all shell rc files (zshenv/zprofile/zshrc/bash_profile/bashrc/profile + /etc variants)
4. All Claude settings.json files (global + project + .local)
5. `type VAR_NAME`, `alias | grep VAR_NAME`
6. Wrapper scripts in every PATH entry

Report what you found in each layer, even empty ones. Don't skip steps.
```

## See Also

- `guides/recipes/evidence-discipline.md` — why guessing costs more than hunting

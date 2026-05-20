# VHS tape for the kimai-everyday README demo.
#
# Prereqs:
#   brew install vhs ttyd ffmpeg
#   pipx install kimai-everyday
#   ~/.config/kimai-everyday/config.toml must already be valid
#     (URL + Kimai token + Anthropic key).
#
# Run:
#   vhs docs/demo.tape
#
# Produces docs/demo.gif. The --dry-run flag means no timesheet entries
# are actually created, so this is safe to re-record.
#
# Things you'll likely want to tweak before recording:
#   - The project / activity filter strings (search for "EDIT:")
#   - The pattern sentence
#   - FontSize / Width / Height if the preview table wraps

Output docs/demo.gif

Set Shell zsh
Set FontSize 16
Set Width 1100
Set Height 700
Set Theme "Catppuccin Mocha"
Set TypingSpeed 60ms
Set PlaybackSpeed 1.0

# Clean prompt so the recording starts on a blank screen.
Hide
Type "clear" Enter
Show

Sleep 800ms
Type "kimai-everyday --dry-run"
Sleep 600ms
Enter

# "Loading projects..." spinner runs for ~500ms-2s depending on Kimai.
Sleep 2500ms

# The autocomplete pre-fills with the last-used project (or the first
# alphabetical one). Ctrl+U clears that default so our Type below
# replaces it instead of appending. Two Downs then move the highlight
# from the input row onto the first filtered match before Enter picks it.
#
# EDIT: type enough of your project name to filter the autocomplete to one match.
Ctrl+U
Type "kimai"
Sleep 800ms
Down 2
Sleep 400ms
Enter

# "Loading activities..." spinner.
Sleep 2000ms

# Same Ctrl+U + Down-twice dance for the activity prompt.
# EDIT: type enough of your activity name to filter to one match.
Ctrl+U
Type "dev"
Sleep 800ms
Down 1
Sleep 400ms
Enter

# Description prompt (optional). Leave blank to keep the demo short.
Sleep 600ms
Enter

# Pattern prompt — this is the headline moment.
Sleep 600ms
Type "every weekday in the first week of June from 09:00 to 12:00 and 13:00 to 17:00"
Sleep 1500ms
Enter

# "Parsing pattern..." (Claude Haiku, usually 1-2s) then preview table.
Sleep 4000ms

# Let the viewer read the preview table.
Sleep 5000ms

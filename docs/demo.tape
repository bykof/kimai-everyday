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
#   - The project / activity hints inside the sentence (search for "kimai" and "dev")
#   - The dates / time blocks
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

# The full one-liner: sentence carries the project/activity hints too.
# EDIT: tweak "kimai" and "dev" so they match a project + activity on your instance.
Sleep 800ms
Type "kimai-everyday --dry-run 'every weekday in the first week of June from 09:00 to 12:00 and 13:00 to 17:00 for project kimai and activity dev'"
Sleep 800ms
Enter

# "Loading catalog..." (3 small HTTP calls in parallel) then "Parsing pattern..."
# (Claude Haiku, usually 1-2s). Banner + preview table follow.
Sleep 5000ms

# Let the viewer read the banner and preview table.
Sleep 7000ms

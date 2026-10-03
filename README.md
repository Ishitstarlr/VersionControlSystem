# MiniGit

MiniGit is a small educational version-control client written in Python. It
implements `init`, `add`, and `commit` without invoking the real Git
executable. It also includes the bonus `log` and `status` commands.

## Requirements

- Python 3.10 or newer
- No third-party packages

## Running MiniGit

Run MiniGit from the folder you want to track. The program file may be kept in
another folder.

```sh
cd /path/to/my-project
python3 /path/to/VersionControl/minigit.py init
```

### Commands

```sh
# Create .minigit/ in the current directory.
python3 /path/to/VersionControl/minigit.py init

# Stage one or more files for the next snapshot.
python3 /path/to/VersionControl/minigit.py add notes.txt src/app.py

# Save the staged snapshot with a message.
python3 /path/to/VersionControl/minigit.py commit -m "Add first notes"

# Display commits, newest first.
python3 /path/to/VersionControl/minigit.py log

# Display staged, modified, deleted, and untracked files.
python3 /path/to/VersionControl/minigit.py status
```

## Storage design

`init` creates a hidden `.minigit/` folder inside the tracked project:

```text
.minigit/
├── objects/      # SHA-256-addressed blob, tree, and commit objects
├── index.json    # staging area: project-relative path -> blob object ID
└── HEAD          # object ID of the most recent commit
```

- A **blob** stores the raw bytes of one file.
- A **tree** stores the staged folder structure and maps filenames to blobs.
- A **commit** stores a tree reference, message, author, timestamp, and parent
  commit reference.

Objects are content-addressed: MiniGit hashes the object type and contents with
SHA-256, then uses the resulting hash as the object filename. Identical content
is therefore stored only once.

## Example workflow

```sh
mkdir demo-project
cd demo-project
echo "Hello MiniGit" > note.txt

python3 /path/to/VersionControl/minigit.py init
python3 /path/to/VersionControl/minigit.py add note.txt
python3 /path/to/VersionControl/minigit.py commit -m "Add note"
python3 /path/to/VersionControl/minigit.py log
python3 /path/to/VersionControl/minigit.py status
```

## Tests

From the `VersionControl` directory, run:

```sh
python3 -m unittest -v
```

The suite covers repository setup, blob storage, nested paths, commit parent
links, `log`, `status`, and common invalid inputs.

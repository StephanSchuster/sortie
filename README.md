# Dashboard polish: try it live

Screenshots show where things are. What the polish is about, how a screen feels when nothing jumps as you move through it, shows only in use. This kit serves the current dashboard and the polished one side by side on the same demo data.

```sh
git clone -b demo-kit --depth 1 https://github.com/StephanSchuster/sortie sortie-demo
cd sortie-demo && ./demo.sh
```

Then open both addresses it prints. The first start takes a few minutes, and Ctrl-C stops everything. `./demo.sh --fresh` starts over.

## What it needs and does

- `git`, `make`, `python3` and the Go version in Sortie's `go.mod`. No Node, because the dashboard's build output is committed.
- It clones both versions into `./work`, builds them with `make build`, and creates ten days of history by running Sortie with its mock agent. No model runs and no token is needed.
- A small local stand-in for the GitHub API supplies the pull requests. Apart from the two clones, nothing leaves your machine.
- All names, issues and figures are sample data.
- The default ports are 7740, 7741, 7749 and 7750. Override them with `BEFORE_PORT`, `AFTER_PORT`, `BUILD_PORT` and `GH_PORT`.

## What to try

1. Click down the rail on each side, with your eyes on the title and the first table. That is the main difference.
2. Make the window wider than 1600 px and go to Pipeline and back, then to Health and back.
3. Drag the window narrower on Overview and watch the Active list: the status column holds its place until the room runs out.
4. Open the same screens at phone width.
5. Open an issue and then its session, and go back with the buttons and with `Esc`.
6. Press `?` and `Ctrl K` to compare the shortcuts and the command palette.

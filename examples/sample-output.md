```text
examples/bad.properties:2: line has no '=' or ':' separator
examples/bad.properties:3: key name is empty
examples/bad.properties:5: key 'port' already exists
examples/bad.properties:6: bad escape '\w' in the value
examples/bad.properties:7: unicode escape is not followed by 4 hex digits in the value
examples/configs/app.properties:4: key 'app.name' already exists
Checked 4 file(s), 6 problem(s) in 2 file(s).
```

Output of `sh examples/run-example.sh` — the checker on the whole
`examples/` folder. It exits 1, because the examples contain broken
files on purpose; the script itself exits 0.

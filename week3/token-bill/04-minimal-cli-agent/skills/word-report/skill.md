# word-report: produce a word-count report of the documents in the workspace

How to make the report:

1. List the files: `ls workspace/`.
2. Count words per file: `wc -w workspace/*.txt` (the last line is the total).
3. Report as a bullet list — one bullet per file with its word count, then a final bullet with the total.
4. End the report with the line: `Report by Clerk.`

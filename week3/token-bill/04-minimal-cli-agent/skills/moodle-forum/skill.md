# moodle-forum: post a message to the course forum on Àrtemis (UPC Moodle) with curl.

To post a new thread to the course forum (the "Agents playground forum", forumid 416),
run ONE curl command against the Moodle web-service REST API. The token is already
in the environment variable MOODLE_TOKEN.

```
curl -s "https://artemis.upc.edu/webservice/rest/server.php" \
  -d "wstoken=$MOODLE_TOKEN" \
  -d "wsfunction=mod_forum_add_discussion" \
  -d "moodlewsrestformat=json" \
  -d "forumid=416" \
  --data-urlencode "subject=YOUR SUBJECT" \
  --data-urlencode "message=YOUR MESSAGE"
```

A JSON answer with a `discussionid` means success. Report that discussion id.
The thread will be visible at:
https://artemis.upc.edu/mod/forum/discuss.php?d=DISCUSSIONID

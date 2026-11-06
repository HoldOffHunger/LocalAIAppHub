# Corpus

Ben's philosophy research library, on http://127.0.0.1:8760, and the 🦉 Corpus entry in the App Hub. Standard-library Python, like the hub.

## What it holds

- **One master list of works.** Each work has every copy Ben has of it: 📕 physical, 💾 digital, 🌐 web. Copies whose main title (before any subtitle) and author's surname agree are one work, so the same book in three formats is listed once (`catalogue.work_key`).
- **What he's read:** unread, reading or read (with the date), and notes.
- **His framework,** in `framework.json`, in his own words: six realms (social, political, economic, religious, educational, ecological) by five phases (principle and observation, revolt, society, hijacked society, revolt against the hijacked society). Any work can be tagged with several of each; the Framework tab is a grid of how many works sit in each square, so the thin ones show.

## Where the books come from

`OWNED_LISTS` in `corpus.py`: the `.rtf` catalogues of books Ben owns, read at every start and by **Read them again** on the Add tab. Only new books are added; nothing already there is touched, and the catalogues themselves are only read. So far that is `E:\Books\Philosophy\New Library Books.rtf` (139 books). The Bookstore, Bundles, Estate Giveaway and Sold lists are books for sale, so they're left out. Web and digital copies are added by hand on the Add tab.

## Still to come

- **Writings:** an index of `E:\Books\Philosophy\Writings` by form and stage.
- **Ask it:** a local model that knows the framework and the reading log, recommending unread works he owns first, then outside books, clearly marked; and suggesting realm and phase tags for him to confirm.
- **Digital copies found on disk:** the PDFs and documents in `Research` and `Resources`.

## Files

| Path | What it is |
|---|---|
| `corpus.py` | The server and the database. |
| `catalogue.py` | Reading the `.rtf` catalogues, and deciding when two copies are one work. |
| `framework.json` | The realms and phases, in Ben's words. |
| `web\index.html` | The page. |
| `data\corpus.sqlite` | Works, copies, reading log and tags. Not in git. |
| `tests\` | `python -m pytest tests` |

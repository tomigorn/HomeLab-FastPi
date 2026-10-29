# Jellyfin home screen

The rows on the Jellyfin start page. They are **the same for everyone** and can't be changed or hidden. A row with nothing to show yet stays visible with a short grey hint.

## Rows, top to bottom
The page comes in groups. The wide rows (Studios, Networks, genres) and the coloured **My List ♥** band sit between them.

| Group | Row | What it shows |
|---|---|---|
| Keep watching | **Continue Watching** | what you started and didn't finish |
| | **Next Up** | the next episode of series you are watching |
| | **Coming soon** | new episodes and films soon: **one card per series with its next episode** (e.g. S03E05 · Thu 5 Nov), soonest week first, the most anticipated first within a week. Already in Jellyfin (earlier episodes, the film): opens its page. Not yet: opens a details page (story, ratings, cast, trailer); it comes by itself |
| — | **My List ♥** | your favourites, as a coloured band |
| New | **Recently Added** (films, series) | the newest additions |
| | **Top 10 Shows in Switzerland** | Netflix's weekly Top 10 series in Switzerland, see [Popular movies and shows](#popular-movies-and-shows) |
| — | **Studios** | browse by film studio (big studios, others once they have 2+ films) |
| Your history | **Recently Watched Movies** | films you finished in the last 60 days |
| | **Recently Watched TV Series & Collections** | only **fully finished** series and **complete** film collections, last 60 days |
| | **Top 10 Movies in Switzerland** | Netflix's weekly Top 10 films in Switzerland |
| — | **Networks** | browse by network (Netflix, HBO, …) |
| For you | **Because you watched …** | similar films and series you haven't seen; **a different title each time** you open the home, favourites more often |
| | **Hidden Gems** | well-rated (IMDb 7.5+), not watched yet |
| — | **Movie Genres** | browse film genres |
| Collections | **Finish These Collections** | collections you started, closest to done first |
| | **Collections** | film collections (e.g. all Harry Potter films) |
| — | **Series Genres** | browse series genres |

## Popular movies and shows
**Popular movies** and **Popular shows** (German: **Beliebte Filme** / **Beliebte Serien**) in the top bar, the side menu or, on the TV, the 🎬 / 📺 buttons next to search. Each opens a page with what streams in Switzerland right now, films or series only:

| Row | Source |
|---|---|
| Top 10 Movies (or Shows) in Switzerland | Netflix's official weekly Top 10 for Switzerland (new every Tuesday) |
| Netflix, Prime Video, Disney+, Apple TV+, Sky, Play Suisse, Paramount+, blue TV | most popular on that service in Switzerland (TMDB, data by JustWatch) |
| Action, Comedy, Drama, … | most popular of the genre on those services (Horror and Romance: films only) |

Every rank is shown; the card says what you can do:

| Card | Means | Press |
|---|---|---|
| normal poster | it is in Jellyfin | the poster to watch it |
| dimmed poster, **1080p / 2160p available** | not here yet, but a good version exists | **🌙 Tonight** (downloads tonight, cheaper power) or **⚡ Now** (at once, daytime power price) |
| dimmed, **🌙 / 🔍 / 📅 / ⬇️** | already requested: waiting for the night / searching / not released yet / downloading | nothing, it comes by itself |
| grey, crossed out in red, **No release yet** | no good version found so far; checked again every night | nothing yet: the buttons appear by themselves once a release exists |

Press the **poster** of a title that isn't here yet: a details page opens (story, IMDb / Rotten Tomatoes / TMDB, cast, trailer) with the same buttons. Trailer: press ▶; if it can't play here, **Open on YouTube**. Back / Esc closes the details, the list stays open.

- Everyone with a Jellyfin account may request here, no Requests login needed. **10 requests per person per 7 days**; the buttons say when the limit is reached.
- A series is requested for the season shown on the card (e.g. **S4**).
- On a computer or TV all 10 cards fit next to each other; on a phone swipe sideways.
- On the TV the two buttons show only **🌙** and **⚡**; the line next to the row title says what they do.
- The lists are refreshed every night; a title shows up in Jellyfin after its download. Details on requests: [Requesting films & series](requests.md).

## Add to My List
Open a film or series and press the **heart** button. It shows up under **My List ♥**. Press the heart again to remove it.

## Row not updating?
| Where | What to do |
|---|---|
| Browser | **Ctrl+Shift+R** (Mac: **Cmd+Shift+R**) |
| TV app | close the app fully and open it again |

!!! info "A finished series isn't in 'Recently Watched' yet?"
    It appears the next time you open the home screen, at the latest a minute later.

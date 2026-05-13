# vermuten
German for "guess", vermuten is a very basic riddle/puzzle application. Upon server start, a config file that contains riddle information is loaded into memory and defines the riddles that a group of classmates must answer.

It is important to note that there is a single instance of this server so, if desired, multiple web browsers can be used to interact with the same game instance.

# Technologies
* Python (language)
* Flask (web framework)
* Gunicorn (web server)
* Heroku (PaaS)

# Configuration
`VERMUTEN_CONFIG` must be set and point to a JSON config file within the root application directory. See `demo.json` for an example of the config format.

# Endpoints
## Game
### /
Returns the puzzle.


## Progress Reset
### /admin/reset
Resets game progress and immediately redirects the user to `/`

# License
Copyright 2021 seaburr

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
# EBS website

Plain HTML, CSS and JavaScript. No install, no build step.

## Run it in Visual Studio Code
1. Open this folder in VS Code (File > Open Folder).
2. Install the "Live Server" extension (Extensions icon in the left bar).
3. Right-click `index.html` > "Open with Live Server". The site reloads each time you save.

(Double-clicking `index.html` also works.)

## Update content
Almost everything lives in **`data/site-data.js`**: stats, team, events, projects, whitepapers, FAQ, email and social links.

- **Add an event:** copy one of the lines in `events`, change the details, delete the `sample: true` part.
- **Add a person:** add a line in the right `team` group.
- **Add a photo:** save it in `images/team/` as the person's name in lowercase with dashes, `.jpg`.
  Example: Celine Cai -> `images/team/celine-cai.jpg`. Portrait orientation (4:5) looks best.
- **Add a whitepaper:** put the PDF in `whitepapers/` and add a line in `whitepapers`.

Page text (mission, services, membership steps) is in each `.html` file.
Colors and fonts are at the top of `css/style.css`.

## Put it online with GitHub Pages
1. Create a repository on GitHub and upload this folder's contents.
2. In the repository: Settings > Pages > Source: "Deploy from a branch", branch `main`, folder `/ (root)`.
3. To use ebsduke.com: enter it under Settings > Pages > Custom domain, then update the DNS records where the domain is registered (GitHub shows which ones).

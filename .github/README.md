# EDSiteProject
A website with various tools for the [Elite Dangerous game](https://www.elitedangerous.com/). This website is a work in progress. A demo version of the website is hosted [here](http://edsite.arthurvanremoortel.me).

In this game you play as a pilot of a spaceship. The game takes place in a very large simulation of the Milky Way with around 400 billion stars and thousands of space stations.
The in-game tools to explore these large amounts of data are very basic and not very useful. This lead to the creation of many community-developed tools.

This website will allow you to explore the large quantities of data from the game, as well as post and share you fleet carrier missions so other players can more easily find good trade opportunities.

## Previews
![Alt text](https://github.com/ArthurVanRemoortel/EDSiteProject/blob/main/.github/img.png?raw=true "Commodities")
![Alt text](https://github.com/ArthurVanRemoortel/EDSiteProject/blob/main/.github/img2.png?raw=true "Commodity search")

## Features
- All users and guests can explore game data. This data is synchronised with the [Elite Dangerous Data Network](https://github.com/EDCD/EDDN)
  - Systems
  - Stations
  - Commodities
  - Rare Items
- Fleet carrier mission:
  - Users can post carrier missions.
  - Carrier missions progress are updated live.
  

TODO:
- Features:
  - Complete system page.
  - Easy copy-paste of object names.
  - Pin/Favorite commodities
  - Regular updates on important commodities
  - Proper login and signup form validation.
    - https://docs.djangoproject.com/en/4.0/topics/auth/customizing/
  - Integration with the official API for user data.
  - Create missions
  - Image Gallery
  - Show price fluctuations of commodities.
  - Remember user location.
  - Live updater needs to update redis cache too.
  - Improvements to autocomplete text.
- Fixes:- 
  - !! Handle listings where station_tradedangerous_id is None
  - Auto background updates
  - Testing
  - Admin tools.
  - Store large data folder outside of docker container.
  - Load slow pages asynchronously.
  - Live updated can sometimes discover new carriers that don't exist yet. Create them with placeholder values for minimal functionality.

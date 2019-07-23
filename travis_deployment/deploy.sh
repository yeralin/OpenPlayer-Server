#!/bin/bash
ssh travis@open-player.dynu.net 'rm -rf /home/travis/OpenPlayer-server/*'
rsync -r --delete-after --exclude 'travis_deployment' --quiet $TRAVIS_BUILD_DIR/* travis@open-player.dynu.net:/home/travis/OpenPlayer-Server/


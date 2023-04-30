// ==UserScript==
// @name         New Userscript
// @namespace    http://tampermonkey.net/
// @version      0.1
// @description  try to take over the world!
// @author       You
// @match        https://open.spotify.com/*
// @icon         https://www.google.com/s2/favicons?sz=64&domain=spotify.com
// @require      https://code.jquery.com/jquery-3.6.0.slim.min.js
// @require      https://gist.githubusercontent.com/raw/2625891/waitForKeyElements.js
// @grant        GM_xmlhttpRequest
// @grant        GM_download
// ==/UserScript==


(function () {
    const extractTrackId = (element) => {
        for (const key of Object.keys(element)) {
            if (key.includes('reactFiber')) {
                const reactState = element[key];
                return reactState.child.memoizedProps['uri'];
            }
        }
    };
    const downloadSong = (trackId) => {
        const url = `https://music.yeralin.net/stream/spotify?trackId=${trackId}&download=true`;
        const headers = {
            Authorization: "Basic ZGFuaXlhcjpkajJndmNQNiVvTiVlcQ=="
        };
        GM_xmlhttpRequest({url, method: "HEAD", headers,
            onload: (response) => {
                const name = response.responseHeaders.match(/(?<=filename=\").*(?=\")/gm)[0];
                GM_download({url, name, headers});
            }
        });
    };

    const appendDownloadButton = (contextMenu) => {
        // Generate Download button
        const ulMenu = contextMenu.children().first();
        let liDownload = ulMenu.children().first().clone();
        liDownload.find('span').text("Download");
        ulMenu.prepend(liDownload);
        // On click listener
        $(liDownload).on("click", () => {
            const contextMenu = $("#context-menu");
            const trackId = extractTrackId(contextMenu[0]);
            contextMenu.parent().hide();
            downloadSong(trackId);
        });
    }
    waitForKeyElements("div#context-menu", appendDownloadButton);
})();
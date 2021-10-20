const Version = (version) => {
    var version = {
        'version': version
    };
    return version;
}

const YouTubeEntry = (title, url) => {
    var youtubeEntry = {
        'title': title,
        'url': url
    }
    return youtubeEntry;
}

export {
    Version,
    YouTubeEntry
};

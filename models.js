function Version(version) {
    var version = {
        'version': version
    };
    return version;
}

function YoutubeEntry(title, url) {
    var youtubeEntry = {
        'title': title,
        'url': url
    }
    return youtubeEntry;
}

module.exports = {
    "Version": Version,
    "YoutubeEntry": YoutubeEntry
};

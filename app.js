"use strict"
require('dotenv').config()

// Dependencies
var express = require('express')
var app = express()
var fs = require('fs')
var ffmpeg = require('fluent-ffmpeg')
var command = ffmpeg()
var YouTube = require('youtube-node')
var youtubedl = require('youtube-dl')
const urlFormatter = require('url')
const Mp3Header = require("mp3-header").Mp3Header

// Models
const { Version, YoutubeEntry } = require('./models')

let PORT = 8000
let BITRATE = 320
let VIDEO_TYPE = 'video'
let MUSIC_CATEGORY = '10'

var youTube = new YouTube()
youTube.setKey(process.env.YOUTUBE_KEY)

app.listen(PORT, function () {
    console.log("OpenPlayer server is listening on port " + PORT)
})

app.get('/version', function (req, res) {
    let versionRes = new Version('0.0.1')
    res.json(versionRes)
})

app.get('/youtube/search', function (req, res) {
    let searchQuery = req.query.q
    if (searchQuery == null) {
        res.status(404).send("Did not suplly 'q' query parameter")
        return
    }
    youTube.search(searchQuery, 50, {
        type: VIDEO_TYPE,
        videoCategoryId: MUSIC_CATEGORY
    }, function (error, result) {
        if (error) {
            res.status(404).send(error)
            return
        }
        var response = []
        for (let item of result['items']) {
            let title = item['snippet']['title']
            let videoId = item['id']['videoId']
            let url = urlFormatter.format({
                protocol: req.protocol,
                host: req.get('host'),
                pathname: '/youtube/stream',
                query: { videoId: videoId }
            })
            let youtubeEntry = new YoutubeEntry(title, url)
            response.push(youtubeEntry)
        }
        res.json(response)
    })
})

function getAudioUrl(videoId, callback) {
    let videoUrl = "https://www.youtube.com/watch?v=" + videoId
    youtubedl.getInfo(videoUrl, [], function(err, payload) {
        if (err) throw err
        callback(payload)
    })
}

app.get('/youtube/stream', function (req, res) {
    let videoId = req.query.videoId
    if (videoId == null) {
        res.status(404).send("Did not suplly 'videoId' query parameter")
        return
    }
    getAudioUrl(videoId, function(payload) {
        var written = 0
        let ffstream = ffmpeg(payload.url)
        .audioCodec('libmp3lame')
        .audioBitrate(BITRATE)
        .format('mp3')
        .on('start', function() {
            var [ hours, mins, secs ] = payload._duration_hms.split(':')
            hours = parseInt(hours)
            mins = parseInt(mins)
            secs = parseInt(secs)
            let totalSeconds = (hours * 60 * 60) + (mins * 60) + secs
            let toBytes = 1000
            let offset = 500
            // Approximating final audio file size
            let expectedByteSize = (totalSeconds * (BITRATE/8)) * toBytes + offset
            res.header({
                'Audio-Duration': totalSeconds,
                'Content-Type': 'audio/mp3',
                'Content-Length': expectedByteSize
            })
        }).on('error', function (err) {
            console.error('An error occurred: ' + err.message)
        }).on('end', function() {
            let expectedByteSize = parseInt(res._headers['content-length'])
            if (expectedByteSize > written) {
                let extra = expectedByteSize - written
                console.log("Not enough bytes were written \"" + expectedByteSize + "\" : \"" + written + "\", writing extra: " + extra)
                res.write(Buffer.alloc(extra))
            }
            console.log('Processing finished')
            res.end()
        }).pipe()

        ffstream.on('data', function(chunk) {
            res.write(chunk)
            written += chunk.length
        })
    })
})

app.get('/api/play/:key', function (req, res) {
    var key = req.params.key
    var music = 'music/' + key + '.mp3'
    var stat = fs.statSync(music)
    var range = req.headers.range
    var readStream
    console.log(req)
    if (range !== undefined) {
        var parts = range.replace(/bytes=/, "").split("-")

        var partial_start = parts[0]
        var partial_end = parts[1]

        if ((isNaN(partial_start) && partial_start.length > 1) || (isNaN(partial_end) && partial_end.length > 1)) {
            return res.sendStatus(500) //ERR_INCOMPLETE_CHUNKED_ENCODING
        }

        var start = parseInt(partial_start, 10)
        var end = partial_end ? parseInt(partial_end, 10) : stat.size - 1
        var content_length = (end - start) + 1

        res.status(206).header({
            'Content-Type': 'audio/mpeg',
            'Content-Length': content_length,
            'Content-Range': "bytes " + start + "-" + end + "/" + stat.size
        })

        readStream = fs.createReadStream(music, {
            start: start,
            end: end
        })
    } else {
        res.header({
            'Content-Type': 'audio/mpeg',
            'Content-Length': stat.size
        })
        readStream = fs.createReadStream(music)
    }
    readStream.pipe(res)
})

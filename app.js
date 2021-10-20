"use strict"
import dotenv from "dotenv";
import express from "express";
import fs from "fs";
import path from "path";
import FFMPEG from "fluent-ffmpeg";
import YouTube from "youtube-node";
import YouTubeDL from "youtube-dl";
import {
    format
} from "url";

// Models
import {
    Version,
    YouTubeEntry
} from "./models.js";

dotenv.config();
const SONGS_DIR = 'songs';
const PORT = 8000;
const BITRATE = 320;
const VIDEO_TYPE = 'video';
const MUSIC_CATEGORY = '10';

const app = express();
const youTube = new YouTube();
youTube.setKey(process.env.YOUTUBE_KEY);

app.listen(PORT, function () {
    console.log("OpenPlayer server is listening on port " + PORT);
});

app.get('/version', function (req, res) {
    res.json(new Version('0.0.2'));
});

app.get('/youtube/search', function (req, res) {
    let searchQuery = req.query.q;
    if (searchQuery == null) {
        res.status(404).send("Did not suplly 'q' query parameter");
        return;
    }
    youTube.search(searchQuery, 50, {
        type: VIDEO_TYPE,
        videoCategoryId: MUSIC_CATEGORY
    }, (error, result) => {
        if (error) {
            res.status(404).send(error);
            return;
        }
        var response = [];
        for (let item of result['items']) {
            let videoId = item['id']['videoId'];
            let youtubeEntry = new YouTubeEntry(item['snippet']['title'], format({
                protocol: req.protocol,
                host: req.get('host'),
                pathname: '/youtube/stream',
                query: {
                    videoId: videoId
                }
            }));
            response.push(youtubeEntry);
        }
        res.json(response);
    })
});

app.get('/youtube/stream', function (req, res) {
    const videoId = req.query.videoId;
    if (videoId == null) {
        res.status(404).send("Did not suplly 'videoId' query parameter");
        return;
    }
    const getAudioUrl = (videoId, callback) => {
        const videoUrl = "https://www.youtube.com/watch?v=" + videoId;
        YouTubeDL.getInfo(videoUrl, [], function (err, payload) {
            if (err) throw err;
            callback(payload);
        })
    };
    getAudioUrl(videoId, function (payload) {
        const localCopy = fs.createWriteStream(`${SONGS_DIR}/${payload.fulltitle}.mp3`);
        var written = 0;
        let ffstream = FFMPEG(payload.url)
            .audioCodec('libmp3lame')
            .audioBitrate(BITRATE)
            .format('mp3')
            .on('start', function () {
                let [hours, mins, secs] = payload._duration_hms.split(':');
                hours = parseInt(hours);
                mins = parseInt(mins);
                secs = parseInt(secs);
                const totalSeconds = (hours * 60 * 60) + (mins * 60) + secs;
                const toBytes = 1000;
                const offset = 500;
                // Approximating final audio file size
                let expectedByteSize = (totalSeconds * (BITRATE / 8)) * toBytes + offset;
                res.header({
                    'Audio-Duration': totalSeconds,
                    'Content-Type': 'audio/mp3',
                    'Content-Length': expectedByteSize
                });
            }).on('error', function (err) {
                console.error('An error occurred: ' + err.message);
            }).on('end', function () {
                let expectedByteSize = parseInt(res.getHeader('content-length'));
                if (expectedByteSize > written) {
                    const extra = expectedByteSize - written;
                    console.log("Not enough bytes were written \"" + expectedByteSize + "\" : \"" + written + "\", writing extra: " + extra);
                    res.write(Buffer.alloc(extra));
                }
                console.log('Processing finished');
                localCopy.end();
                res.end();
            }).pipe();

        ffstream.on('data', function (chunk) {
            localCopy.write(chunk);
            res.write(chunk);
            written += chunk.length;
        });
    })
});

app.get('/', (req, res) => {
    const songs = [];
    fs.readdirSync(SONGS_DIR).forEach(file => {
        if (path.extname(file) === '.mp3') {
            songs.push(format({
                protocol: req.protocol,
                host: req.get('host'),
                pathname: 'local/stream',
                query: {
                    songId: file
                }
            }));
        }
    });
    res.json({
        songs
    });
});

app.get('/local/stream', function (req, res) {
    const songId = req.query.songId;
    if (songId == null) {
        res.status(404).send("Did not suplly 'songId' query parameter");
        return;
    }
    const music = `${SONGS_DIR}/${songId}`;
    const stat = fs.statSync(music);
    const range = req.headers.range;
    var readStream;
    if (range !== undefined) {
        var parts = range.replace(/bytes=/, "").split("-");

        var partial_start = parts[0];
        var partial_end = parts[1];

        if ((isNaN(partial_start) && partial_start.length > 1) || (isNaN(partial_end) && partial_end.length > 1)) {
            return res.sendStatus(500); //ERR_INCOMPLETE_CHUNKED_ENCODING
        }

        const start = parseInt(partial_start, 10);
        const end = partial_end ? parseInt(partial_end, 10) : stat.size - 1;
        const content_length = (end - start) + 1;

        res.status(206).header({
            'Content-Type': 'audio/mpeg',
            'Content-Length': content_length,
            'Content-Range': "bytes " + start + "-" + end + "/" + stat.size
        });

        readStream = fs.createReadStream(music, {
            start: start,
            end: end
        });
    } else {
        res.header({
            'Content-Type': 'audio/mpeg',
            'Content-Length': stat.size
        });
        readStream = fs.createReadStream(music);
    }
    readStream.pipe(res);
});

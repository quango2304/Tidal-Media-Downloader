#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@File    :   download.py
@Time    :   2020/11/08
@Author  :   Yaronzz
@Version :   1.0
@Contact :   yaronhuang@foxmail.com
@Desc    :
'''

from concurrent.futures import ThreadPoolExecutor

from decryption import *
from printf import *
from tidal import *


def __isSkip__(finalpath, url):
    if not SETTINGS.checkExist:
        return False
    curSize = aigpy.file.getSize(finalpath)
    if curSize <= 0:
        return False
    netSize = aigpy.net.getSize(url)
    return curSize >= netSize


def __encrypted__(stream, srcPath, descPath):
    if aigpy.string.isNull(stream.encryptionKey):
        os.replace(srcPath, descPath)
    else:
        key, nonce = decrypt_security_token(stream.encryptionKey)
        decrypt_file(srcPath, descPath, key, nonce)
        os.remove(srcPath)


def __parseContributors__(roleType, Contributors):
    if Contributors is None:
        return None
    try:
        ret = []
        for item in Contributors['items']:
            if item['role'] == roleType:
                ret.append(item['name'])
        return ret
    except:
        return None


def __setMetaData__(track: Track, album: Album, filepath, contributors, lyrics):
    obj = aigpy.tag.TagTool(filepath)
    obj.album = track.album.title
    obj.title = track.title
    if not aigpy.string.isNull(track.version):
        obj.title += ' (' + track.version + ')'

    obj.artist = list(map(lambda artist: artist.name, track.artists))
    obj.copyright = track.copyRight
    obj.tracknumber = track.trackNumber
    obj.discnumber = track.volumeNumber
    obj.composer = __parseContributors__('Composer', contributors)
    obj.isrc = track.isrc

    obj.albumartist = list(map(lambda artist: artist.name, album.artists))
    obj.date = album.releaseDate
    obj.totaldisc = album.numberOfVolumes
    obj.lyrics = lyrics
    if obj.totaldisc <= 1:
        obj.totaltrack = album.numberOfTracks
    coverpath = TIDAL_API.getCoverUrl(album.cover, "1280", "1280")
    obj.save(coverpath)


def downloadCover(album):
    if album is None:
        return
    path = getAlbumPath(album) + '/cover.jpg'
    url = TIDAL_API.getCoverUrl(album.cover, "1280", "1280")
    aigpy.net.downloadFile(url, path)


def downloadAlbumInfo(album, tracks):
    if album is None:
        return

    path = getAlbumPath(album)
    aigpy.path.mkdirs(path)

    path += '/AlbumInfo.txt'
    infos = ""
    infos += "[ID]          %s\n" % (str(album.id))
    infos += "[Title]       %s\n" % (str(album.title))
    infos += "[Artists]     %s\n" % (TIDAL_API.getArtistsName(album.artists))
    infos += "[ReleaseDate] %s\n" % (str(album.releaseDate))
    infos += "[SongNum]     %s\n" % (str(album.numberOfTracks))
    infos += "[Duration]    %s\n" % (str(album.duration))
    infos += '\n'

    for index in range(0, album.numberOfVolumes):
        volumeNumber = index + 1
        infos += f"===========CD {volumeNumber}=============\n"
        for item in tracks:
            if item.volumeNumber != volumeNumber:
                continue
            infos += '{:<8}'.format("[%d]" % item.trackNumber)
            infos += "%s\n" % item.title
    aigpy.file.write(path, infos, "w+")


def downloadVideo(video: Video, album: Album = None, playlist: Playlist = None):
    try:
        stream = TIDAL_API.getVideoStreamUrl(video.id, SETTINGS.videoQuality)
        path = getVideoPath(video, album, playlist)

        Printf.video(video, stream)
        logging.info("[DL Video] name=" + aigpy.path.getFileName(path) + "\nurl=" + stream.m3u8Url)

        m3u8content = requests.get(stream.m3u8Url).content
        if m3u8content is None:
            Printf.err(f"DL Video[{video.title}] getM3u8 failed.{str(e)}")
            return False, f"GetM3u8 failed.{str(e)}"

        urls = aigpy.m3u8.parseTsUrls(m3u8content)
        if len(urls) <= 0:
            Printf.err(f"DL Video[{video.title}] getTsUrls failed.{str(e)}")
            return False, "GetTsUrls failed.{str(e)}"

        check, msg = aigpy.m3u8.downloadByTsUrls(urls, path)
        if check:
            Printf.success(video.title)
            return True
        else:
            Printf.err(f"DL Video[{video.title}] failed.{msg}")
            return False, msg
    except Exception as e:
        Printf.err(f"DL Video[{video.title}] failed.{str(e)}")
        return False, str(e)


def downloadTrack(track: Track, album=None, playlist=None, userProgress=None, partSize=1048576):
    qualities = [AudioQuality.Max, AudioQuality.Master, AudioQuality.HiFi, AudioQuality.High, AudioQuality.Normal]
    last_error = ''

    for quality in qualities:
        try:
            # Attempt to get the stream URL for the current quality
            stream = TIDAL_API.getStreamUrl(track.id, quality)
            path = getTrackPath(track, stream, album, playlist)

            if SETTINGS.showTrackInfo and not SETTINGS.multiThread:
                Printf.track(track, stream)

            if userProgress is not None:
                userProgress.updateStream(stream)

            # Log the download attempt
            logging.info(f"[DL Track] name={aigpy.path.getFileName(path)}\nurl={stream.url}")

            # Initialize the download tool
            tool = aigpy.download.DownloadTool(path + '.part', stream.urls)
            tool.setUserProgress(userProgress)
            tool.setPartSize(partSize)
            check, err = tool.start(SETTINGS.showProgress and not SETTINGS.multiThread)

            if not check:
                raise Exception(f"Download failed: {str(err)}")

            # Decrypt the downloaded file if it's encrypted
            __encrypted__(stream, path + '.part', path)

            # Fetch contributors
            try:
                contributors = TIDAL_API.getTrackContributors(track.id)
            except Exception as e:
                logging.warning(f"Failed to get contributors for track '{track.title}': {e}")
                contributors = None

            # Fetch lyrics
            lyrics = ''

            # Set metadata for the downloaded track
            __setMetaData__(track, album, path, contributors, lyrics)
            Printf.success(f"Downloaded '{track.title}' with quality '{quality}'")
            return True, ''

        except Exception as e:
            # Log the error for this quality attempt
            logging.error(f"Failed to download '{track.title}' with quality '{quality}': {e}")
            last_error = str(e)
            # Continue to try the next lower quality
            continue

    # After all quality attempts have failed
    Printf.err(f"All download attempts failed for track '{track.title}'. Last error: {last_error}")
    return False, last_error



def downloadTracks(tracks, album: Album = None, playlist: Playlist = None):
    def __getAlbum__(item: Track):
        album = TIDAL_API.getAlbum(item.album.id)
        if SETTINGS.saveCovers and not SETTINGS.usePlaylistFolder:
            downloadCover(album)
        return album

    if not SETTINGS.multiThread:
        for index, item in enumerate(tracks):
            itemAlbum = album
            if itemAlbum is None:
                itemAlbum = __getAlbum__(item)
                item.trackNumberOnPlaylist = index + 1
            downloadTrack(item, itemAlbum, playlist)
    else:
        thread_pool = ThreadPoolExecutor(max_workers=5)
        for index, item in enumerate(tracks):
            itemAlbum = album
            if itemAlbum is None:
                itemAlbum = __getAlbum__(item)
                item.trackNumberOnPlaylist = index + 1
            thread_pool.submit(downloadTrack, item, itemAlbum, playlist)
        thread_pool.shutdown(wait=True)


def downloadVideos(videos, album: Album, playlist=None):
    for item in videos:
        downloadVideo(item, album, playlist)

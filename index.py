from flask import Flask, render_template, request, make_response
from pytube import YouTube
import os
import json
import time
import requests
import logging
import trafilatura
import numpy as np
import mysql.connector
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

logging.basicConfig(level=logging.INFO)

API_KEY = '2b79cdad5fb64b1cb4091006a167e7b2'
app = Flask(__name__)

app.config['SEND_FILE_MAX_AGE_DEFAULT'] = -1

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'yash123',
    'database': 'collegeProject',
    'auth_plugin': 'mysql_native_password'
}

# Connect to the database
conn = mysql.connector.connect(**db_config)

# Create a cursor object
cursor = conn.cursor()

@app.route('/')
def main():
    return render_template("register.html")


@app.route("/register", methods=['GET'])
def registerGet():
    return render_template("register.html")


@app.route("/register", methods=['POST'])
def register():
    username = request.form['username']
    email = request.form['email']
    password = request.form['password']
    confirmpassword = request.form['confirmpassword']
    
    if password != confirmpassword:
        return "<script>alert('Passwords do not match. Please try again.'); window.history.back();</script>"
    
    password_hash = generate_password_hash(password)
    
    try:
        add_user(username, email, password_hash)
    except IntegrityError:
        return "<script>alert('Email already exists. Please use a different email.'); window.history.back();</script>"
        
    print(username, email)
    return "<script>alert('Registration successful!'); window.location.href='/login';</script>"


def add_user(username, email, password):
    cursor.execute('INSERT INTO users (username, email, password) VALUES (%s, %s, %s)', (username, email, password))
    conn.commit()
    
def add_words(email, final):
    final_str = ', '.join(final)
    cursor.execute('UPDATE users SET final = %s WHERE email = %s', (final_str, email))
    conn.commit()

@app.route("/login", methods=['GET'])
def loginGet():
    return render_template("login.html")


@app.route("/login", methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']
    
    # Fetch the user's hashed password from the database
    cursor.execute('SELECT password FROM users WHERE email = %s', (email,))
    result = cursor.fetchone()
    
    if result is None:
        return "<script>alert('Invalid email'); window.history.back();</script>"
    hashed_password = result[0]
    print(email, password, hashed_password)
    # Validate the password hash
    if check_password_hash(hashed_password, password):
        resp = make_response(render_template("index.html"))
        resp.set_cookie('userID',email)
        return resp
    else:
        return "<script>alert('Invalid password'); window.history.back();</script>"


@app.route("/video", methods=['GET','POST'])
def video():
    if request.method == "POST":
        try:
            os.remove('cron.mp3')
            os.remove('transcript.txt')
            os.remove('transcript_chapters.json')
            os.remove('transcript_highlights.json')
        except OSError:
            pass
        url = request.form.get("url")
        url = url.split('&')[0]
        yt = YouTube(str(url))
        video = yt.streams.filter(only_audio=True).first()
        destination = '.'
        out_file = video.download(output_path=destination)
        base, ext = os.path.splitext(out_file)
        new_file = 'cron.mp3'
        os.rename(out_file, new_file)

        class AutoYouTubeTimestamp:
            def __init__(self):
                self.__endpoint_upload = 'https://api.assemblyai.com/v2/upload'
                self.__endpoint_transcript = 'https://api.assemblyai.com/v2/transcript'
                self.__headers_auth = {
                    'authorization': API_KEY
                }
                self.__headers = {
                    'authorization': API_KEY,
                    'content-type': 'application/json'
                }
                self.__chunk_size = 5242880

            def __upload(self, filename: str) -> str:
                def read_file(filename: str):
                    with open(filename, 'rb') as f:
                        while True:
                            data = f.read(self.__chunk_size)
                            if not data:
                                break
                            yield data

                logging.info(f"{datetime.now()} - Started uploading audio file...")
                upload_response = requests.post(
                    url=self.__endpoint_upload,
                    headers=self.__headers_auth,
                    data=read_file(filename)
                )
                logging.info(f"{datetime.now()} - Audio file uploaded! URL = {upload_response.json()['upload_url']}")
                return upload_response.json()['upload_url']

            def __transcribe(self, audio_url: str) -> str:
                logging.info(f"{datetime.now()} - Started transcribing audio file...")

                transcript_response = requests.post(
                    url=self.__endpoint_transcript,
                    headers=self.__headers,
                    json={
                        'audio_url': audio_url,
                        'auto_chapters': True,
                        'auto_highlights': True
                    }
                )
                logging.info(f"{datetime.now()} - Audio file transcribed! ID = {transcript_response.json()['id']}")
                return transcript_response.json()['id']

            def __poll(self, transcript_id: str) -> None:
                def get_response(transcript_id: str):
                    polling_endpoint = f"{self.__endpoint_transcript}/{transcript_id}"
                    polling_response = requests.get(
                        url=polling_endpoint,
                        headers=self.__headers
                    )
                    return polling_response

                def save(transcript_id: str):
                    fname_transcript = f"{transcript_id}.txt"
                    fname_chapters = f"{transcript_id}_chapters.json"
                    fname_highlights = f"{transcript_id}_highlights.json"

                    with open(fname_transcript, 'w') as f:
                        f.write(polling_response.json()['text'])
                        logging.info(f"{datetime.now()} - Transcript saved to {fname_transcript}")

                    with open(fname_chapters, 'w') as f:
                        chapters = polling_response.json()['chapters']
                        json.dump(chapters, f, indent=4)
                        logging.info(f"{datetime.now()} - Transcript chapters saved to {fname_chapters}")

                    with open(fname_highlights, 'w') as f:
                        highlights = polling_response.json()['auto_highlights_result']
                        json.dump(highlights, f, indent=4)
                        logging.info(f"{datetime.now()} - Transcript highlights saved to {fname_highlights}")

                    logging.info(f"{datetime.now()} - All files saved successfully")

                finished = False
                while not finished:
                    polling_response = get_response(transcript_id=transcript_id)
                    if polling_response.json()['status'] == 'completed':
                        save(transcript_id='transcript')
                        finished = True
                    else:
                        logging.warning(
                            f"{datetime.now()} - Transcribing still in progress - Trying again in 30 seconds.")
                        time.sleep(30)

            def run(self, filename: str) -> None:
                audio_url = self.__upload(filename)
                transcribe_id = self.__transcribe(audio_url)
                self.__poll(transcribe_id)

        ats = AutoYouTubeTimestamp()
        ats.run('cron.mp3')
        array_text = open("transcript.txt", "r")
        array_text = array_text.read()
        array_text = [array_text]

        # BERT
        from keybert import KeyBERT
        kw_extractor = KeyBERT('distilbert-base-nli-mean-tokens')
        for j in range(len(array_text)):
            keywords = kw_extractor.extract_keywords(array_text[j], stop_words='english')
            keywords_list = list(dict(keywords).keys())

        # Yake
        from yake import KeywordExtractor
        kw_extractor = KeywordExtractor(lan="en", n=1, top=5)
        for j in range(len(array_text)):
            keywords = kw_extractor.extract_keywords(text=array_text[j])
            keywords = [x for x, y in keywords]

        final = set()
        final.update(keywords + keywords_list)
        final = list(final)
        final.sort()
        email = request.cookies.get('userID')
        add_words(email, final)

        # Wiki
        import wikipediaapi
        summary = {}
        wiki_wiki = wikipediaapi.Wikipedia('en')
        for i in range(len(final)):
            page_py = wiki_wiki.page(final[i])
            summary[final[i].title()] = page_py.summary.rsplit(". ")[0]
            print("Summary: ", str(final), summary, "\n")
        return render_template("summary.html", sumi=summary, url=url)

    return render_template("video.html")


if __name__ == "__main__":
    app.run(debug=False)

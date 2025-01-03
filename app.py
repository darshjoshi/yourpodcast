import streamlit as st
import openai
import subprocess
import os
import re
from pathlib import Path
from io import StringIO
import openai
from PyPDF2 import PdfReader
import docx

openai.api_key = os.getenv("OPENAI_API_KEY")


# --------------------------------------------------------------
# 1) Configure your OpenAI key here or via environment variable
# --------------------------------------------------------------
# If you prefer an environment variable approach, comment out the next line.
# e.g., `export OPENAI_API_KEY="sk-..."` in your shell before running Streamlit


#openai.api_key = "YOUR_OPENAI_API_KEY"

# --------------------------------------------------------------
# 2) Hypothetical TTS client (OpenAI does NOT have this method yet)
#    You must replace this with a real TTS solution in production.
# --------------------------------------------------------------
from openai import OpenAI  

#def get_tts_client():

    #return OpenAI(api_key=OPENAI_API_KEY)

# --------------------------------------------------------------
# 3) Speaker-to-voice dictionary (hardcoded, no user input).
#    We'll assume exactly two voices: Host -> 'shimmer', Responder -> 'onyx'.
# --------------------------------------------------------------
SPEAKER_TO_VOICE = {
    "Host": "nova",
    "Responder": "onyx",
}

# --------------------------------------------------------------
# 4) Convert user text/article into an interactive podcast script 
#    with two roles: "Host" and "Responder", using GPT-3.5 Turbo.
# --------------------------------------------------------------
def generate_podcast_script(original_text: str) -> str:
    """
    Use ChatCompletion (GPT-3.5-Turbo) to turn any text into 
    a conversation between "Host" and "Responder".
    """
    system_prompt = (
        "You are a helpful assistant that transforms raw text or articles into "
        "a lively, interactive podcast script featuring exactly two speakers: "
        "'Host' and 'Responder'. Use a conversational style, ensuring the text "
        "is logically divided into sections where 'Host' leads the discussion, "
        "and 'Responder' provides insights or answers. Maintain clarity, accuracy, "
        "and coherence while making it sound like an engaging podcast. show excitement and enthusiasm in both the host and responder!"
    )

    user_prompt = f"""Rewrite the following text into an interactive conversation 
    with two roles: 'Host' and 'Responder'. Make sure to include speaker labels 
    clearly at the start of each paragraph (e.g. "Host: ...", "Responder: ..."). Also, keep in mind that the conversation MUST happen with an imagenary female name for host and male name for responder, this can not be forgotten.

    TEXT:
    {original_text}
    """

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,
        max_tokens=2048
    )

    generated_script = response.choices[0].message.content.strip()
    return generated_script

# --------------------------------------------------------------
# 5) Parse the final "Host/Responder" script 
#    into a structured list of segments: [{"speaker":..., "text":...}, ...]
# --------------------------------------------------------------
def parse_script_into_segments(script_text: str):
    """
    Expects the script in format:
      Host: Some text...
      Responder: Some text...
    Returns a list of dicts: [{ 'speaker': 'Host', 'text': '...' }, ...]
    """
    # Split by newlines
    lines = script_text.strip().split("\n")

    segments = []
    current_speaker = None
    current_text = []

    speaker_pattern = re.compile(r"^([A-Za-z]+):\s*(.*)")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        match = speaker_pattern.match(line)
        if match:
            # If we have existing text, push to segments
            if current_speaker and current_text:
                segments.append({
                    "speaker": current_speaker,
                    "text": " ".join(current_text)
                })
                current_text = []

            # New speaker line
            current_speaker = match.group(1)
            text_after_colon = match.group(2)
            current_text.append(text_after_colon)

        else:
            # Continuation of current speaker's text
            if current_speaker:
                current_text.append(line)

    # End of script: flush last segment
    if current_speaker and current_text:
        segments.append({
            "speaker": current_speaker,
            "text": " ".join(current_text)
        })

    return segments

# --------------------------------------------------------------
# 6) Automatically chunk text to handle TTS limits (we won't ask user)
# --------------------------------------------------------------
def auto_chunk_text(text: str, max_chunk_size=1500):
    """
    Splits text into smaller chunks if it exceeds some length (e.g. 1500 chars).
    Return a list of chunk strings.
    """
    words = text.split()
    chunks = []
    tmp = []

    current_length = 0
    for word in words:
        if current_length + len(word) + 1 > max_chunk_size:
            chunks.append(" ".join(tmp))
            tmp = [word]
            current_length = len(word)
        else:
            tmp.append(word)
            current_length += len(word) + 1

    if tmp:
        chunks.append(" ".join(tmp))

    return chunks

# --------------------------------------------------------------
# 7) Create individual TTS segments (MP3 files)
# --------------------------------------------------------------
def create_speech_segment(client, speaker, text, seg_index, chunk_index):
    # Map speaker to voice
    voice = SPEAKER_TO_VOICE.get(speaker, "alloy")  # fallback if not found
    output_filename = f"temp_segment_{seg_index}_{chunk_index}_{speaker}.mp3"

    # Hypothetical TTS call to a single "tts-1" model
    response = client.audio.speech.create(
        model="tts-1",   # fixed, as requested
        voice=voice,
        input=text
    )
    response.stream_to_file(output_filename)

    return output_filename

# --------------------------------------------------------------
# 8) Merge all TTS segments into one file and remove the temp segments
# --------------------------------------------------------------
def merge_audio_files(mp3_files, output_filename="final_podcast.mp3"):
    list_file = Path("temp_mp3_list.txt")
    with list_file.open("w", encoding="utf-8") as f:
        for mp3 in mp3_files:
            f.write(f"file '{mp3}'\n")

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        output_filename
    ]
    subprocess.run(cmd, check=True)

    # Clean up
    list_file.unlink()
    for mp3 in mp3_files:
        os.remove(mp3)

    return output_filename

# --------------------------------------------------------------
# 9) The main Streamlit app
# --------------------------------------------------------------
def main():
    st.title("Interactive Podcast Generator")
    st.write(
        "Convert any text or uploaded file into a two-speaker podcast using GPT-3.5 "
        "and a single TTS model (tts-1)."
    )

    # Input method: text or file
    input_mode = st.radio("How will you provide the text?", ["Text", "File"], horizontal=True)
    text_data = ""

    if input_mode == "Text":
        text_data = st.text_area("Enter your text/article here:", height=250)
    else:
        uploaded_file = st.file_uploader("Upload a text, PDF, or DOCX file", type=["txt", "pdf", "docx"])
        if uploaded_file is not None:
            if uploaded_file.type == "text/plain":
                text_data = uploaded_file.read().decode("utf-8")
            elif uploaded_file.type == "application/pdf":
                pdf_reader = PdfReader(uploaded_file)
                text_data = "\n".join(page.extract_text() for page in pdf_reader.pages)
            elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                doc = docx.Document(uploaded_file)
                text_data = "\n".join(paragraph.text for paragraph in doc.paragraphs)

    if st.button("Generate Podcast"):
        if not text_data.strip():
            st.warning("Please provide some text or upload a file before generating.")
            return

        with st.spinner("Converting your text into an interactive podcast script..."):
            # 1) Use GPT-3.5 to turn the user text into a Host/Responder script
            script = generate_podcast_script(text_data)

        with st.expander("Generated Script (Debug / Info)"):
            st.write(script)

        with st.spinner("Parsing script and generating audio..."):
            # 2) Parse the script into segments
            segments = parse_script_into_segments(script)
            # 3) Prepare TTS client
            client = OpenAI(api_key=openai.api_key)

            mp3_files = []
            total_segments = len(segments)
            seg_counter = 0

            progress_bar = st.progress(0)

            for i, seg in enumerate(segments):
                speaker = seg["speaker"]
                segment_text = seg["text"]

                # 4) Auto-chunk if text is too large
                sub_chunks = auto_chunk_text(segment_text, max_chunk_size=1500)

                for j, chunk_text in enumerate(sub_chunks):
                    filename = create_speech_segment(client, speaker, chunk_text, i, j)
                    mp3_files.append(filename)

                seg_counter += 1
                progress_bar.progress(int((seg_counter / total_segments) * 100))

            # 5) Merge all segments
            final_filename = merge_audio_files(mp3_files, "final_podcast.mp3")

        st.success("Podcast generated successfully!")
        # Provide audio player
        audio_file = open(final_filename, "rb")
        audio_bytes = audio_file.read()
        st.audio(audio_bytes, format="audio/mp3")

        # Provide download
        st.download_button(
            label="Download Podcast",
            data=audio_bytes,
            file_name=final_filename,
            mime="audio/mp3"
        )


if __name__ == "__main__":
    main()

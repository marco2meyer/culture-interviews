import time
import os
import config
from utils import save_interview_data
import toml

# Load API library
if "gpt" in config.MODEL.lower():
    api = "openai"
    from openai import OpenAI

elif "claude" in config.MODEL.lower():
    api = "anthropic"
    import anthropic
else:
    raise ValueError(
        "Model does not contain 'gpt' or 'claude'; unable to determine API."
    )

# Path to the secrets file
secrets_path = os.path.join(os.path.dirname(__file__), '.streamlit', 'secrets.toml')

# Load secrets from the TOML file
try:
    secrets = toml.load(secrets_path)
    openai_api_key = secrets.get("API_KEY_OPENAI")
    anthropic_api_key = secrets.get("API_KEY_ANTHROPIC")
except FileNotFoundError:
    print(f"Error: Secrets file not found at {secrets_path}")
    print("Please create a .streamlit/secrets.toml file with your API keys.")
    exit()
except Exception as e:
    print(f"Error loading secrets: {e}")
    exit()

# Load API client
if api == "openai":
    if not openai_api_key:
        print("Error: API_KEY_OPENAI not found in secrets.toml")
        exit()
    client = OpenAI(api_key=openai_api_key)
elif api == "anthropic":
    if not anthropic_api_key:
        print("Error: API_KEY_ANTHROPIC not found in secrets.toml")
        exit()
    client = anthropic.Anthropic(api_key=anthropic_api_key)

def call_api_with_retry(api_call_func, *args, **kwargs):
    """Calls an API function with a retry mechanism for rate limit errors."""
    retry_delays = [1, 10, 30]
    for i, delay in enumerate(retry_delays):
        try:
            return api_call_func(*args, **kwargs)
        except (anthropic.RateLimitError, openai.RateLimitError) as e:
            print(f"Rate limit exceeded. Retrying in {delay} seconds... (Attempt {i + 1}/{len(retry_delays)})")
            time.sleep(delay)
    print("API call failed after multiple retries. Terminating interview.")
    return None


def run_simulation():
    """Runs the interview simulation."""

    # Create directories if they do not already exist
    for directory in [config.TRANSCRIPTS_DIRECTORY, config.TIMES_DIRECTORY, config.BACKUPS_DIRECTORY]:
        if not os.path.exists(directory):
            os.makedirs(directory)

    # Loop through each persona
    for persona_name, persona_description in config.PERSONAS.items():
        print(f"Running interviews for persona: {persona_name}")

        # Run the specified number of interviews for the persona
        for i in range(config.INTERVIEWS_PER_PERSONA):
            print(f"  Starting interview {i + 1}/{config.INTERVIEWS_PER_PERSONA}")

            # Initialise interview state
            messages = []
            start_time = time.time()
            start_time_file_names = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(start_time))
            interview_active = True
            conversation_turn = 0

            # Generate a unique username for the interview
            username = f"{persona_name.replace(' ', '_')}_{i + 1}"

            # Start with the interviewer's opening message
            if api == "openai":
                messages.append({"role": "system", "content": config.SYSTEM_PROMPT})
                completion = call_api_with_retry(
                    client.chat.completions.create,
                    messages=messages,
                    model=config.MODEL,
                    max_tokens=config.MAX_OUTPUT_TOKENS,
                    temperature=config.TEMPERATURE,
                )
                message_interviewer = completion.choices[0].message.content if completion else None
            elif api == "anthropic":
                messages.append({"role": "user", "content": "Hi"})
                response = call_api_with_retry(
                    client.messages.create,
                    system=config.SYSTEM_PROMPT,
                    messages=messages,
                    model=config.MODEL,
                    max_tokens=config.MAX_OUTPUT_TOKENS,
                    temperature=config.TEMPERATURE,
                )
                message_interviewer = response.content[0].text if response else None

            if message_interviewer is None:
                interview_active = False
                messages.append({"role": "assistant", "content": "Interview terminated due to API rate limits."})
            else:
                messages.append({"role": "assistant", "content": message_interviewer})
                print(f"    Interviewer: {message_interviewer}")

            # Main conversation loop
            while interview_active and conversation_turn < config.MAX_CONVERSATION_TURNS:
                conversation_turn += 1

                # Respondent's turn
                respondent_system_prompt = config.RESPONDENT_SYSTEM_PROMPT.format(
                    persona_name=persona_name, persona_description=persona_description
                )
                if api == "openai":
                    respondent_messages = messages.copy()
                    respondent_messages[0] = {"role": "system", "content": respondent_system_prompt}
                    completion = call_api_with_retry(
                        client.chat.completions.create,
                        messages=respondent_messages,
                        model=config.MODEL,
                        max_tokens=config.MAX_OUTPUT_TOKENS,
                        temperature=config.TEMPERATURE,
                    )
                    message_respondent = completion.choices[0].message.content if completion else None
                elif api == "anthropic":
                    response = call_api_with_retry(
                        client.messages.create,
                        system=respondent_system_prompt,
                        messages=messages,
                        model=config.MODEL,
                        max_tokens=config.MAX_OUTPUT_TOKENS,
                        temperature=config.TEMPERATURE,
                    )
                    message_respondent = response.content[0].text if response else None
                
                if message_respondent is None:
                    interview_active = False
                    messages.append({"role": "user", "content": "Interview terminated due to API rate limits."})
                else:
                    messages.append({"role": "user", "content": message_respondent})
                    print(f"    {persona_name}: {message_respondent}")

                # Interviewer's turn
                if api == "openai":
                    completion = call_api_with_retry(
                        client.chat.completions.create,
                        messages=messages,
                        model=config.MODEL,
                        max_tokens=config.MAX_OUTPUT_TOKENS,
                        temperature=config.TEMPERATURE,
                    )
                    message_interviewer = completion.choices[0].message.content if completion else None
                elif api == "anthropic":
                    response = call_api_with_retry(
                        client.messages.create,
                        system=config.SYSTEM_PROMPT,
                        messages=messages,
                        model=config.MODEL,
                        max_tokens=config.MAX_OUTPUT_TOKENS,
                        temperature=config.TEMPERATURE,
                    )
                    message_interviewer = response.content[0].text if response else None

                if message_interviewer is None:
                    interview_active = False
                    messages.append({"role": "assistant", "content": "Interview terminated due to API rate limits."})
                # Check for closing codes
                elif any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                    interview_active = False
                    closing_code = next(code for code in config.CLOSING_MESSAGES.keys() if code in message_interviewer)
                    closing_message = config.CLOSING_MESSAGES[closing_code]
                    messages.append({"role": "assistant", "content": closing_message})
                    print(f"    Interviewer: {closing_message}")
                else:
                    messages.append({"role": "assistant", "content": message_interviewer})
                    print(f"    Interviewer: {message_interviewer}")

            # Save the final interview data
            save_interview_data(
                username=username,
                transcripts_directory=config.TRANSCRIPTS_DIRECTORY,
                times_directory=config.TIMES_DIRECTORY,
                messages=messages,
                start_time=start_time,
            )
            print(f"  Interview {i + 1} for {persona_name} completed and saved.")

if __name__ == "__main__":
    run_simulation()

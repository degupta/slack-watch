from slackclient import SlackClient
import os
import time
import re
import traceback
import json

TITLE_LINK  = "title_link"
REACTION    = "reaction"
TIMESTAMP   = "ts"
ITEM        = "item"
CHANNEL     = "channel"
TYPE        = "type"
ATTACHMENTS = "attachments"
MESSAGE     = "message"
TEXT        = "text"

REACTION_EYES    = "eyes"
REACTION_ADDED   = "reaction_added"
REACTION_REMOVED = "reaction_removed"
DISPLAY_NAME     = "display_name"

LISTENER_USER    = "user"
LISTENER_CHANNEL = "channel"

BITBUCKET_PR_MSG_KEY = "BITBUCKET_PR:"

LISTENERS    = {}
MSG_CACHE    = {}
USER_CACHE   = {}

MY_BOT_ID = "B78KJFP54"

slack_api_client = SlackClient(os.environ["SLACK_API_TOKEN"])

def call_slack_for_msg(msg_ts, channel):
	try:
		return slack_api_client.api_call(
			"channels.history",
			channel=channel,
			latest=msg_ts,
			inclusive=True,
			count=1
		)['messages'][0]
	except Exception as e:
		print "Error calling slack API %s" % (e)
		traceback.print_exc()
		return None

def call_slack_for_user(user):
	try:
		return slack_api_client.api_call(
			"users.info",
			user=user
		).get(LISTENER_USER).get('profile')
	except Exception as e:
		print "Error calling slack API to get user %s" % (e)
		traceback.print_exc()
		return None

def post_message_to_channel(channel, message):
	try:
		print ("Sending to channel %s : %s") % (channel, message)
		slack_api_client.api_call(
			"chat.postMessage",
			channel=channel,
			text=message
		)
	except Exception as e:
		print "Error calling slack API %s" % (e)
		traceback.print_exc()

def post_message_thread_to_channel(channel, msg_ts, thread_message):
	try:
		print ("Sending to channel %s : %s") % (channel, thread_message)
		slack_api_client.api_call(
			"chat.postMessage",
			channel=channel,
			text=thread_message,
			thread_ts=msg_ts
		)
	except Exception as e:
		print "Error calling slack API %s" % (e)
		traceback.print_exc()

def get_user(user_id):
	if USER_CACHE.get(user_id) is None:
		u = call_slack_for_user(user_id)
		if u:
			USER_CACHE[user_id] = u

	return USER_CACHE.get(user_id)

def check_for_bitbucket_pr(text):
	pr = re.match(r'.*bitbucket\.org/.*\/(.*)\/pull\-requests\/(\d+).*', text)
	if pr and len(pr.groups()) == 2:
		return BITBUCKET_PR_MSG_KEY + pr.groups()[0] + ":" + pr.groups()[1]
	return None

def get_message_key(msg):
	if not msg:
		return None

	if msg.get(ATTACHMENTS):
		for attachment in msg[ATTACHMENTS]:
			if attachment.get(TITLE_LINK):
				key = check_for_bitbucket_pr(attachment[TITLE_LINK])
				if key: return key

	if msg.get(TEXT):
		key = check_for_bitbucket_pr(msg[TEXT])
		if key: return key

	return None


def get_message(msg_ts, channel):
	if MSG_CACHE.get(msg_ts) is None:
		msg = call_slack_for_msg(msg_ts, channel)
		if msg:
			MSG_CACHE[msg_ts] = msg
	return MSG_CACHE.get(msg_ts)

def get_message_listeners(key, channel):
	return (LISTENERS.get(key) or []) if key else []

def read_in_listeners():
	if os.path.isfile('listeners.json'):
		listeners = open('listeners.json', 'r').read()
		global LISTENERS
		LISTENERS = json.loads(listeners)
		print "LISTENERS : %s" % (LISTENERS)

def write_message_listeners():
	listeners = json.dumps(LISTENERS)
	target = open('listeners.json', 'w')
	target.write(listeners)

def add_message_listener(key, listener):
	if LISTENERS.get(key) is None:
		LISTENERS[key] = []
	LISTENERS[key].extend([listener])
	print "Adding Listener for key %s : %s" % (key, listener)
	write_message_listeners()

def remove_message_listener(key, user):
	listeners = LISTENERS.get(key) or []
	size = len(listeners)
	listeners = [x for x in listeners if x[LISTENER_USER] != user]
	if len(listeners) == 0 and LISTENERS.get(key):
		del LISTENERS[key]
	else:
		LISTENERS[key] = listeners
	print "Removing %s Listener(s) for key %s : %s" % (size - len(listeners), key, user)
	write_message_listeners()

def handle_reaction_message(msg, user_id, channel):
	if msg.get(REACTION) == REACTION_EYES and user_id:
		orig_msg_ts = msg[ITEM][TIMESTAMP]
		orig_msg_key = get_message_key(get_message(orig_msg_ts, channel))

		if orig_msg_key is None:
			print ("Could not get original message for reaction : %s") % (orig_msg_ts)
			return

		channel = msg[ITEM][CHANNEL]
		message_prefix = "watching"
		if msg[TYPE] == REACTION_ADDED:
			add_message_listener(orig_msg_key, {LISTENER_USER: user_id, LISTENER_CHANNEL: channel})
		elif msg[TYPE] == REACTION_REMOVED:
			message_prefix = "stopped watching"
			remove_message_listener(orig_msg_key, user_id)

		user = get_user(user_id) or {}
		post_message_thread_to_channel(channel, orig_msg_ts, "Okay %s <@%s|%s> " % (message_prefix, user_id, user.get(DISPLAY_NAME) or  user_id))


def process_message(msg):
	msg_type = msg.get(TYPE)
	if msg_type in ('presence_change', 'reconnect_url', 'hello'):
		return

	if msg.get('bot_id') == MY_BOT_ID:
		return

	msg_ts = msg.get(TIMESTAMP)
	key = get_message_key(msg)
	if key:
		MSG_CACHE[msg_ts] = msg
		print ("Got a message with key %s") % (key);

	user = msg.get(LISTENER_USER)
	if user is None and msg.get(MESSAGE):
		user = msg[MESSAGE].get(LISTENER_USER)

	channel = msg.get(LISTENER_CHANNEL)
	if channel is None and msg.get(ITEM):
		channel = msg[ITEM].get(LISTENER_CHANNEL)

	if channel is None:
		print ("Got a message without channel : %s") % (msg)
		return

	if msg.get(REACTION):
		if user:
			handle_reaction_message(msg, user, channel)
		else:
			print ("Got a message without user : %s") % (msg)
	else:
		print msg
		listeners = get_message_listeners(key, channel)
		if listeners:
			post_msg = "Ping"
			text = msg[ATTACHMENTS][0].get(TEXT) if msg.get(ATTACHMENTS) and len(msg[ATTACHMENTS]) > 0 else ""
			text = msg.get(TEXT) if (text is None or text == "") else text

			for listener in listeners:
				user_id = listener[LISTENER_USER]
				user = get_user(user_id)
				if user:
					post_msg = post_msg + " <@" + user_id + "|" + user[DISPLAY_NAME] + ">"
			post_msg = post_msg + (" " + (text or ""))
			post_message_thread_to_channel(channel, msg_ts, post_msg)

if __name__ == "__main__":
	read_in_listeners()
	num_errors = 0
	while num_errors < 10:
		slack_rtm_client = SlackClient(os.environ["SLACK_RTM_TOKEN"])
		if slack_rtm_client.rtm_connect():
			print "Connected to Slack..."
			num_errors = 0
			while True:
				msgs = slack_rtm_client.rtm_read()
				if len(msgs) > 0:
					for msg in msgs:
						try:
							process_message(msg)
						except Exception as e:
							print "Error processing %s : %s" % (msg, e)
							traceback.print_exc()
				time.sleep(1)
		else:
			num_errors += 1
			print "Connection Failed : %s" (num_errors)
			time.sleep(5)
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Copyright (C) 2016 Wildfire Games.
 * This file is part of 0 A.D.
 *
 * 0 A.D. is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 2 of the License, or
 * (at your option) any later version.
 *
 * 0 A.D. is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with 0 A.D.  If not, see <http://www.gnu.org/licenses/>.
"""

import logging, time, traceback
from optparse import OptionParser

import sleekxmpp
from sleekxmpp.stanza import Iq
from sleekxmpp.xmlstream import ElementBase, register_stanza_plugin, ET
from sleekxmpp.xmlstream.handler import Callback
from sleekxmpp.xmlstream.matcher import StanzaPath

## Class to tracks all games in the lobby ##
class GameList():
  def __init__(self):
    self.gameList = {}
  def addGame(self, JID, data):
    """
      Add a game
    """
    data['players-init'] = data['players']
    data['nbp-init'] = data['nbp']
    data['state'] = 'init'
    self.gameList[str(JID)] = data
  def removeGame(self, JID):
    """
      Remove a game attached to a JID
    """
    del self.gameList[str(JID)]
  def getAllGames(self):
    """
      Returns all games
    """
    return self.gameList
  def changeGameState(self, JID, data):
    """
      Switch game state between running and waiting
    """
    JID = str(JID)
    if JID in self.gameList:
      if self.gameList[JID]['nbp-init'] > data['nbp']:
        logging.debug("change game (%s) state from %s to %s", JID, self.gameList[JID]['state'], 'waiting')
        self.gameList[JID]['state'] = 'waiting'
      else:
        logging.debug("change game (%s) state from %s to %s", JID, self.gameList[JID]['state'], 'running')
        self.gameList[JID]['state'] = 'running'
      self.gameList[JID]['nbp'] = data['nbp']
      self.gameList[JID]['players'] = data['players']
      if 'startTime' not in self.gameList[JID]: 
        self.gameList[JID]['startTime'] = str(round(time.time())) 

## Class for custom player stanza extension ##
class PlayerXmppPlugin(ElementBase):
  name = 'query'
  namespace = 'jabber:iq:player'
  interfaces = set(('online'))
  sub_interfaces = interfaces
  plugin_attrib = 'player'

  def addPlayerOnline(self, player):
    playerXml = ET.fromstring("<online>%s</online>" % player)
    self.xml.append(playerXml)

## Class for custom gamelist stanza extension ##
class GameListXmppPlugin(ElementBase):
  name = 'query'
  namespace = 'jabber:iq:gamelist'
  interfaces = set(('game', 'command'))
  sub_interfaces = interfaces
  plugin_attrib = 'gamelist'

  def addGame(self, data):
    itemXml = ET.Element("game", data)
    self.xml.append(itemXml)

  def getGame(self):
    """
      Required to parse incoming stanzas with this
        extension.
    """
    game = self.xml.find('{%s}game' % self.namespace)
    data = {}
    for key, item in game.items():
      data[key] = item
    return data

## Class for custom boardlist and ratinglist stanza extension ##
class BoardListXmppPlugin(ElementBase):
  name = 'query'
  namespace = 'jabber:iq:boardlist'
  interfaces = set(('board', 'command', 'recipient'))
  sub_interfaces = interfaces
  plugin_attrib = 'boardlist'
  def addCommand(self, command):
    commandXml = ET.fromstring("<command>%s</command>" % command)
    self.xml.append(commandXml)
  def addRecipient(self, recipient):
    recipientXml = ET.fromstring("<recipient>%s</recipient>" % recipient)
    self.xml.append(recipientXml)
  def addItem(self, name, rating):
    itemXml = ET.Element("board", {"name": name, "rating": rating})
    self.xml.append(itemXml)

## Class for custom gamereport stanza extension ##
class GameReportXmppPlugin(ElementBase):
  name = 'report'
  namespace = 'jabber:iq:gamereport'
  plugin_attrib = 'gamereport'
  interfaces = ('game', 'sender')
  sub_interfaces = interfaces
  def addSender(self, sender):
    senderXml = ET.fromstring("<sender>%s</sender>" % sender)
    self.xml.append(senderXml)
  def addGame(self, gr):
    game = ET.fromstring(str(gr)).find('{%s}game' % self.namespace)
    self.xml.append(game)
  def getGame(self):
    """
      Required to parse incoming stanzas with this
        extension.
    """
    game = self.xml.find('{%s}game' % self.namespace)
    data = {}
    for key, item in game.items():
      data[key] = item
    return data

## Class for custom profile ##
class ProfileXmppPlugin(ElementBase):
  name = 'query'
  namespace = 'jabber:iq:profile'
  interfaces = set(('profile', 'command', 'recipient'))
  sub_interfaces = interfaces
  plugin_attrib = 'profile'
  def addCommand(self, command):
    commandXml = ET.fromstring("<command>%s</command>" % command)
    self.xml.append(commandXml)
  def addRecipient(self, recipient):
    recipientXml = ET.fromstring("<recipient>%s</recipient>" % recipient)
    self.xml.append(recipientXml)
  def addItem(self, player, rating, highestRating, rank, totalGamesPlayed, wins, losses):
    itemXml = ET.Element("profile", {"player": player, "rating": rating, "highestRating": highestRating,
                                      "rank" : rank, "totalGamesPlayed" : totalGamesPlayed, "wins" : wins,
                                      "losses" : losses})
    self.xml.append(itemXml)

## Main class which handles IQ data and sends new data ##
class XpartaMuPP(sleekxmpp.ClientXMPP):
  """
  A simple list provider
  """
  def __init__(self, sjid, password, room, nick, ratingsbot):
    sleekxmpp.ClientXMPP.__init__(self, sjid, password)
    self.sjid = sjid
    self.room = room
    self.nick = nick
    self.ratingsBotWarned = False

    self.ratingsBot = ratingsbot
    # Game collection
    self.gameList = GameList()

    # Store mapping of nicks and XmppIDs, attached via presence stanza
    self.nicks = {}
    self.presences = {} # Obselete when XEP-0060 is implemented.
    self.affiliations = {}
    self.muted = set()

    self.lastLeft = ""

    register_stanza_plugin(Iq, PlayerXmppPlugin)
    register_stanza_plugin(Iq, GameListXmppPlugin)
    register_stanza_plugin(Iq, BoardListXmppPlugin)
    register_stanza_plugin(Iq, GameReportXmppPlugin)
    register_stanza_plugin(Iq, ProfileXmppPlugin)

    self.register_handler(Callback('Iq Player',
                                       StanzaPath('iq/player'),
                                       self.iqhandler,
                                       instream=True))
    self.register_handler(Callback('Iq Gamelist',
                                       StanzaPath('iq/gamelist'),
                                       self.iqhandler,
                                       instream=True))
    self.register_handler(Callback('Iq Boardlist',
                                       StanzaPath('iq/boardlist'),
                                       self.iqhandler,
                                       instream=True))
    self.register_handler(Callback('Iq GameReport',
                                       StanzaPath('iq/gamereport'),
                                       self.iqhandler,
                                       instream=True))
    self.register_handler(Callback('Iq Profile',
                                       StanzaPath('iq/profile'),
                                       self.iqhandler,
                                       instream=True))

    self.add_event_handler("session_start", self.start)
    self.add_event_handler("muc::%s::got_online" % self.room, self.muc_online)
    self.add_event_handler("muc::%s::got_offline" % self.room, self.muc_offline)
    self.add_event_handler("groupchat_message", self.muc_message)
    self.add_event_handler("changed_status", self.presence_change)

  def start(self, event):
    """
    Process the session_start event
    """
    self.plugin['xep_0045'].joinMUC(self.room, self.nick)
    self.send_presence()
    self.get_roster()
    logging.info("XpartaMuPP started")

  def muc_online(self, presence):
    """
    Process presence stanza from a chat room.
    """
    if self.ratingsBot in self.nicks:
      self.relayRatingListRequest(self.ratingsBot)
    self.relayPlayerOnline(presence['muc']['jid'])
    if presence['muc']['nick'] != self.nick:
      # If it doesn't already exist, store player JID mapped to their nick.
      jid = str(presence['muc']['jid'])
      if jid not in self.nicks:
        self.nicks[jid] = presence['muc']['nick']
        self.presences[jid] = "available"
        self.affiliations[jid] = presence['muc']['affiliation'];
        if jid.split("/")[0] in self.muted:
          self.setRole(self.room, jid, None, 'visitor', '', None)
      # Check the jid isn't already in the lobby.
      # Send Gamelist to new player.
      self.sendGameList(presence['muc']['jid'])
      logging.debug("Client '%s' connected with a nick of '%s'." %(presence['muc']['jid'], presence['muc']['nick']))

  def muc_offline(self, presence):
    """
    Process presence stanza from a chat room.
    """
    # Clean up after a player leaves
    if presence['muc']['nick'] != self.nick:
      # Delete any games they were hosting.
      for JID in self.gameList.getAllGames():
        if JID == str(presence['muc']['jid']):
          self.gameList.removeGame(JID)
          self.sendGameList()
          break
      # Remove them from the local player list.
      self.lastLeft = str(presence['muc']['jid'])
      if str(presence['muc']['jid']) in self.nicks:
        del self.nicks[str(presence['muc']['jid'])]
        del self.presences[str(presence['muc']['jid'])]
        del self.affiliations[str(presence['muc']['jid'])]
    if presence['muc']['nick'] == self.ratingsBot:
      self.ratingsBotWarned = False

  def muc_message(self, msg):
    """
    Process new messages from the chatroom.
    """
    if msg['mucnick'] == self.nick:
      return
    lowercase_message = msg['body'].lower()
    if self.nick.lower() in lowercase_message:
      self.send_message(mto=msg['from'].bare,
                        mbody="I am the administrative bot in this lobby and cannot participate in any games.",
                        mtype='groupchat')

    speaker_jid = self.get_jid(msg['mucnick'], False)
    if lowercase_message[:6] == "@mute " and (self.affiliations[speaker_jid] == "owner" or
                                              self.affiliations[speaker_jid] == "admin"):
      if len(lowercase_message.split(" ")) == 2:
        muted_nick = lowercase_message.split(" ")[1];
        muted_jid = self.get_jid(muted_nick, True);
        if muted_nick == self.nick:
          self.send_message(mto=msg['from'].bare,
                            mbody="I refuse to mute myself!",
                            mtype='groupchat')
        if muted_jid is None:
          self.send_message(mto=msg['from'].bare,
                            mbody="Unknown user.",
                            mtype='groupchat')
        elif self.affiliations[muted_jid] == "owner" or self.affiliations[muted_jid] == "admin":
          self.send_message(mto=msg['from'].bare,
                            mbody="You cannot mute a moderator.",
                            mtype='groupchat')
        else:
          self.muted.add(muted_jid)
          self.send_message(mto=msg['from'].bare,
                            mbody="[MODERATION] " + muted_nick + " has been muted by " + msg['mucnick'],
                            mtype='groupchat')
          self.setRole(self.room, muted_jid, None, 'visitor', '', None)
      else:
        self.send_message(mto=msg['from'].bare,
                          mbody="Invalid syntax.",
                          mtype='groupchat')
    elif lowercase_message[:8] == "@unmute " and (self.affiliations[speaker_jid] == "owner" or
                                              self.affiliations[speaker_jid] == "admin"):
      if len(lowercase_message.split(" ")) == 2:
        muted_nick = lowercase_message.split(" ")[1];
        muted_jid = self.get_jid(muted_nick, True);
        if muted_jid in self.muted:
          self.muted.remove(muted_jid)
          self.send_message(mto=msg['from'].bare,
                            mbody="[MODERATION] " + muted_nick + " has been unmuted by " + msg['mucnick'],
                            mtype='groupchat')
          self.setRole(self.room, muted_jid, None, 'participant', '', None)
        else:
          
          self.send_message(mto=msg['from'].bare,
                            mbody=muted_nick + " is not currently muted.",
                            mtype='groupchat')
      else:
        self.send_message(mto=msg['from'].bare,
                          mbody="Invalid syntax.",
                          mtype='groupchat')
    
  def get_jid(self, nick, strip_resource):
    """
    Retrives the corresponding jid from a nick
    """
    for jid in self.nicks:
      if self.nicks[jid].lower() == nick.lower():
        if strip_resource:
          return jid.split("/")[0]
        else:
          return jid
    return None

  def presence_change(self, presence):
    """
    Processes presence change
    """
    prefix = "%s/" % self.room
    nick = str(presence['from']).replace(prefix, "")
    for JID in self.nicks:
      if self.nicks[JID] == nick:
        if self.presences[JID] == 'busy' and (str(presence['type']) == "available" or str(presence['type']) == "away"):
          self.sendGameList(JID)
          self.relayBoardListRequest(JID)
        self.presences[JID] = str(presence['type'])
        break

  def setRole(self, room, jid=None, nick=None, role='participant', reason='',ifrom=None):
     """
     Alter room Role. Taken from https://github.com/fritzy/SleekXMPP/pull/161
     """
     if role not in ('none','visitor','participant','moderator'):
       raise TypeError
     query = ET.Element('{http://jabber.org/protocol/muc#admin}query')
     if nick is not None:
       item = ET.Element('item', {'role':role, 'nick':nick})
     else:
       item = ET.Element('item', {'role':role, 'jid':jid})
     ritem = ET.SubElement(item, 'reason')
     ritem.text=reason
     query.append(item)
     iq = self.makeIqSet(query)
     iq['to'] = room
     iq['from'] = ifrom
     # For now, swallow errors to preserve existing API
     try:
       result = iq.send()
     except IqError:
       return False
     except IqTimeout:
       return False
     return True
 

  def iqhandler(self, iq):
    """
    Handle the custom stanzas
      This method should be very robust because we could receive anything
    """
    if iq['type'] == 'error':
      logging.error('iqhandler error' + iq['error']['condition'])
      #self.disconnect()
    elif iq['type'] == 'get':
      """
      Request lists.
      """
      # Send lists/register on leaderboard; depreciated once muc_online
      #  can send lists/register automatically on joining the room.
      if list(iq.plugins.items())[0][0][0] == 'gamelist':
        try:
          self.sendGameList(iq['from'])
        except:
          traceback.print_exc()
          logging.error("Failed to process gamelist request from %s" % iq['from'].bare)
      elif list(iq.plugins.items())[0][0][0] == 'boardlist':
        command = iq['boardlist']['command']
        try:
          self.relayBoardListRequest(iq['from'])
        except:
          traceback.print_exc()
          logging.error("Failed to process leaderboardlist request from %s" % iq['from'].bare)
      elif list(iq.plugins.items())[0][0][0] == 'profile':
        command = iq['profile']['command']
        try:
          self.relayProfileRequest(iq['from'], command)
        except:
          pass
      else:
        logging.error("Unknown 'get' type stanza request from %s" % iq['from'].bare)
    elif iq['type'] == 'result':
      """
      Iq successfully received
      """
      if list(iq.plugins.items())[0][0][0] == 'boardlist':
        recipient = iq['boardlist']['recipient']
        self.relayBoardList(iq['boardlist'], recipient)
      elif list(iq.plugins.items())[0][0][0] == 'profile':
        recipient = iq['profile']['recipient']
        player =  iq['profile']['command']
        self.relayProfile(iq['profile'], player, recipient)
      else:
        pass
    elif iq['type'] == 'set':
      if list(iq.plugins.items())[0][0][0] == 'gamelist':
        """
        Register-update / unregister a game
        """
        command = iq['gamelist']['command']
        if command == 'register':
          # Add game
          try:
            if iq['from'] in self.nicks:
              self.gameList.addGame(iq['from'], iq['gamelist']['game'])
              self.sendGameList()
          except:
            traceback.print_exc()
            logging.error("Failed to process game registration data")
        elif command == 'unregister':
          # Remove game
          try:
            self.gameList.removeGame(iq['from'])
            self.sendGameList()
          except:
            traceback.print_exc()
            logging.error("Failed to process game unregistration data")

        elif command == 'changestate':
          # Change game status (waiting/running)
          try:
            self.gameList.changeGameState(iq['from'], iq['gamelist']['game'])
            self.sendGameList()
          except:
            traceback.print_exc()
            logging.error("Failed to process changestate data. Trying to add game")
            try:
              if iq['from'] in self.nicks:
                self.gameList.addGame(iq['from'], iq['gamelist']['game'])
                self.sendGameList()
            except:
              pass
        else:
          logging.error("Failed to process command '%s' received from %s" % command, iq['from'].bare)
      elif list(iq.plugins.items())[0][0][0] == 'gamereport':
        """
        Client is reporting end of game statistics
        """
        try:
          self.relayGameReport(iq['gamereport'], iq['from'])
        except:
          traceback.print_exc()
          logging.error("Failed to update game statistics for %s" % iq['from'].bare)
    else:
       logging.error("Failed to process stanza type '%s' received from %s" % iq['type'], iq['from'].bare)

  def sendGameList(self, to = ""):
    """
      Send a massive stanza with the whole game list.
      If no target is passed the gamelist is broadcasted
        to all clients.
    """
    games = self.gameList.getAllGames()
    
    stz = GameListXmppPlugin()

    ## Pull games and add each to the stanza        
    for JIDs in games:
      g = games[JIDs]
      stz.addGame(g)

    ## Set additional IQ attributes
    iq = self.Iq()
    iq['type'] = 'result'
    iq.setPayload(stz)
    if to == "":
      for JID in list(self.presences):
        if self.presences[JID] != "available" and self.presences[JID] != "away":
          continue
        iq['to'] = JID

        ## Try sending the stanza
        try:
          iq.send(block=False, now=True)
        except:
          logging.error("Failed to send game list")
    else:
      ## Check recipient exists
      if str(to) not in self.nicks:
        logging.error("No player with the XmPP ID '%s' known to send gamelist to." % str(to))
        return
      iq['to'] = to

      ## Try sending the stanza
      try:
        iq.send(block=False, now=True)
      except:
        logging.error("Failed to send game list")

  def relayBoardListRequest(self, recipient):
    """
      Send a boardListRequest to EcheLOn.
    """
    to = self.ratingsBot
    if to not in self.nicks:
      self.warnRatingsBotOffline()
      return
    stz = BoardListXmppPlugin()
    iq = self.Iq()
    iq['type'] = 'get'
    stz.addCommand('getleaderboard')
    stz.addRecipient(recipient)
    iq.setPayload(stz)
    ## Set additional IQ attributes
    iq['to'] = to
    ## Try sending the stanza
    try:
      iq.send(block=False, now=True)
    except:
      logging.error("Failed to send leaderboard list request")
      
  def relayRatingListRequest(self, recipient):
    """
      Send a ratingListRequest to EcheLOn.
    """
    to = self.ratingsBot
    if to not in self.nicks:
      self.warnRatingsBotOffline()
      return
    stz = BoardListXmppPlugin()
    iq = self.Iq()
    iq['type'] = 'get'
    stz.addCommand('getratinglist')
    iq.setPayload(stz)
    ## Set additional IQ attributes
    iq['to'] = to
    ## Try sending the stanza
    try:
      iq.send(block=False, now=True)
    except:
      logging.error("Failed to send rating list request")
  
  def relayProfileRequest(self, recipient, player):
    """
      Send a profileRequest to EcheLOn.
    """
    to = self.ratingsBot
    if to not in self.nicks:
      self.warnRatingsBotOffline()
      return
    stz = ProfileXmppPlugin()
    iq = self.Iq()
    iq['type'] = 'get'
    stz.addCommand(player)
    stz.addRecipient(recipient)
    iq.setPayload(stz)
    ## Set additional IQ attributes
    iq['to'] = to
    ## Try sending the stanza
    try:
      iq.send(block=False, now=True)
    except:
      logging.error("Failed to send profile request")

  def relayPlayerOnline(self, jid):
    """
      Tells EcheLOn that someone comes online.
    """
    ## Check recipient exists
    to = self.ratingsBot
    if to not in self.nicks:
      return
    stz = PlayerXmppPlugin()
    iq = self.Iq()
    iq['type'] = 'set'
    stz.addPlayerOnline(jid)
    iq.setPayload(stz)
    ## Set additional IQ attributes
    iq['to'] = to
    ## Try sending the stanza
    try:
      iq.send(block=False, now=True)
    except:
      logging.error("Failed to send player muc online")
      
  def relayGameReport(self, data, sender):
    """
      Relay a game report to EcheLOn.
    """
    to = self.ratingsBot
    if to not in self.nicks:
      self.warnRatingsBotOffline()
      return
    stz = GameReportXmppPlugin()
    stz.addGame(data)
    stz.addSender(sender)
    iq = self.Iq()
    iq['type'] = 'set'
    iq.setPayload(stz)
    ## Set additional IQ attributes
    iq['to'] = to
    ## Try sending the stanza
    try:
      iq.send(block=False, now=True)
    except:
      logging.error("Failed to send game report request")

  def relayBoardList(self, boardList, to = ""):
    """
      Send the whole leaderboard list.
      If no target is passed the boardlist is broadcasted
        to all clients.
    """
    iq = self.Iq()
    iq['type'] = 'result'
    iq.setPayload(boardList)
    ## Check recipient exists
    if to == "":  
      # Rating List
      for JID in list(self.presences):
        if self.presences[JID] != "available" and self.presences[JID] != "away":
          continue
        ## Set additional IQ attributes
        iq['to'] = JID
        ## Try sending the stanza
        try:
          iq.send(block=False, now=True)
        except:
          logging.error("Failed to send rating list")
    else:
      # Leaderboard or targeted rating list
      if str(to) not in self.nicks:
        logging.error("No player with the XmPP ID '%s' known to send boardlist to" % str(to))
        return
      ## Set additional IQ attributes
      iq['to'] = to
      ## Try sending the stanza
      try:
        iq.send(block=False, now=True)
      except:
        logging.error("Failed to send leaderboard list")

  def relayProfile(self, data, player, to):
    """
      Send the player profile to a specified target.
    """
    if to == "":
      logging.error("Failed to send profile, target unspecified")
      return

    iq = self.Iq()
    iq['type'] = 'result'
    iq.setPayload(data)
    ## Check recipient exists
    if str(to) not in self.nicks:
      logging.error("No player with the XmPP ID '%s' known to send profile to" % str(to))
      return

    ## Set additional IQ attributes
    iq['to'] = to

    ## Try sending the stanza
    try:
      iq.send(block=False, now=True)
    except:
      traceback.print_exc()
      logging.error("Failed to send profile")

  def warnRatingsBotOffline(self):
    """
      Warns that the ratings bot is offline.
    """
    if not self.ratingsBotWarned:
      logging.warn("Ratings bot '%s' is offline" % str(self.ratingsBot))
      self.ratingsBotWarned = True

## Main Program ##
if __name__ == '__main__':
  # Setup the command line arguments.
  optp = OptionParser()

  # Output verbosity options.
  optp.add_option('-q', '--quiet', help='set logging to ERROR',
                  action='store_const', dest='loglevel',
                  const=logging.ERROR, default=logging.INFO)
  optp.add_option('-d', '--debug', help='set logging to DEBUG',
                  action='store_const', dest='loglevel',
                  const=logging.DEBUG, default=logging.INFO)
  optp.add_option('-v', '--verbose', help='set logging to COMM',
                  action='store_const', dest='loglevel',
                  const=5, default=logging.INFO)

  # XpartaMuPP configuration options
  optp.add_option('-m', '--domain', help='set xpartamupp domain',
                  action='store', dest='xdomain',
                  default="lobby.wildfiregames.com")
  optp.add_option('-l', '--login', help='set xpartamupp login',
                  action='store', dest='xlogin',
                  default="xpartamupp")
  optp.add_option('-p', '--password', help='set xpartamupp password',
                  action='store', dest='xpassword',
                  default="XXXXXX")
  optp.add_option('-n', '--nickname', help='set xpartamupp nickname',
                  action='store', dest='xnickname',
                  default="WFGbot")
  optp.add_option('-r', '--room', help='set muc room to join',
                  action='store', dest='xroom',
                  default="arena")
  optp.add_option('-e', '--elo', help='set rating bot username',
                  action='store', dest='xratingsbot',
                  default="disabled")

  opts, args = optp.parse_args()

  # Setup logging.
  logging.basicConfig(level=opts.loglevel,
                      format='%(asctime)s        %(levelname)-8s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

  # XpartaMuPP
  xmpp = XpartaMuPP(opts.xlogin+'@'+opts.xdomain+'/CC', opts.xpassword, opts.xroom+'@conference.'+opts.xdomain, opts.xnickname, opts.xratingsbot+'@'+opts.xdomain+'/CC')
  xmpp.register_plugin('xep_0030') # Service Discovery
  xmpp.register_plugin('xep_0004') # Data Forms
  xmpp.register_plugin('xep_0045') # Multi-User Chat	# used
  xmpp.register_plugin('xep_0060') # PubSub
  xmpp.register_plugin('xep_0199') # XMPP Ping

  if xmpp.connect():
    xmpp.process(threaded=False)
  else:
    logging.error("Unable to connect")

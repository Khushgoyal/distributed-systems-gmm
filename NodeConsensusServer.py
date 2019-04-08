import sys
import time
import json
import uuid
import socket
import thread
import random
import pickle
import logging
import threading
from multiprocessing import Process

from KThread import *
from messages.append_entries_messages import AppendEntriesMessage
from messages.vote_messages import RequestForVoteMessage
from messages.config_messages import ServerConfig
from messages.base_message import BaseMessage
from AcceptorFile import *

from commons.Constants import DEBUG, SERVER_NODE_GROUP_NAME

logger = logging.getLogger(__name__)

class Server(object):
    def __init__(self, id_):
        self.id = id_
        self.friendlyName = self._formFriendlyName(id_)
        self.configFile = 'config-%d' % self.id
        logger.debug('Server Init. Config File = {}'.format(self.configFile))
        self.role = 'follower'
        self.commitIndex = 0
        self.lastApplied = 0
        self.leaderID = 0
        address = json.load(file('config.json'))
        port_list = address['AddressBook']
        running = address['running']
        self.initialState = {}
        # self.initialState = 100
        self.addressbook = {}
        for id_ in running:
            self.addressbook[id_] = port_list[id_ - 1]
            
        # need to put it into file later on
        self.load()


        self.port = self.addressbook[self.id]
        self.request_votes = self.peers[:]

        self.numVotes = 0
        self.oldVotes = 0
        self.newVotes = 0

        self.lastLogIndex = 0
        self.lastLogTerm = 0

        self.listener = KThread(target = self.listen, args= (acceptor,))
        self.listener.start()
        logger.debug('Started listening on port {}'.format(self.port))

        self.during_change = 0
        self.newPeers = []
        self.new = None
        self.old = None

    def listen(self, on_accept):
        logger.info('Server Listen Method')
        srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv.bind(("", self.port))
        print 'start listenning ', self.id, " ", self.currentTerm
        while True:
            data,addr = srv.recvfrom(1024)
            #print 'listening ', self.id
            thr = KThread(target=on_accept, args=(self,data,addr))
            thr.start()
        srv.close()

    def follower(self):
        logger.info('Server Follower Method')
        print ' '
        print '*************************'
        print 'Running as a follower ', self.id, " ", self.currentTerm
        print 'My ID is ', self.id
        print "The terms is ", self.currentTerm
        print "My Peers are ", self.peers
        print '*************************'
        self.role = 'follower'
        self.last_update = time.time()
        election_timeout = 5 * random.random() + 5
        while time.time() - self.last_update <= election_timeout:
            pass
        self.startElection()
        while True:
            self.last_update = time.time()
            election_timeout = 5 * random.random() + 5
            while time.time() - self.last_update <= election_timeout:
                pass

            if self.election.is_alive():
                self.election.kill()
            self.startElection()

    def startElection(self):
        print 'Server startElection Method ', self.id, " ", self.currentTerm
        self.role = 'candidate'
        self.election = KThread(target =self.threadElection, args = ())
        if len(self.peers) != 0:
            self.currentTerm += 1
            self.votedFor = self.id
            self.save()
            self.numVotes = 1
            if self.during_change == 1:
                self.newVotes = 0
                self.oldVotes = 0
                if self.id in self.new:
                    self.newVotes = 1
                if self.id in self.old:
                    self.oldVotes = 1
            elif self.during_change == 2:
                self.newVotes = 0
                if self.id in self.new:
                    self.newVotes = 1
            self.election.start()

    def threadElection(self):
        logger.info('Server threadElection Method')
        print 'timeouts, start a new election with term %d' % self.currentTerm
        self.role = 'candidate'
        self.request_votes = self.peers[:]
        sender = self.id

        while 1:
            for peer in self.peers:
                if peer in self.request_votes:
                    Msg = str(self.lastLogTerm) + ' ' + str(self.lastLogIndex)
                    msg = RequestForVoteMessage(sender, peer, self.currentTerm, Msg)
                    data = pickle.dumps(msg)
                    sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                    sock.sendto(data, ("", self.addressbook[peer]))
            time.sleep(1) # wait for servers to receive

    def leader(self):
        logger.info('Server leader Method')
        print ' '
        print '*************************'
        print 'Running as a leader'
        print 'My ID is ', self.id
        print "The terms is ", self.currentTerm
        print "My Peers are ", self.peers
        print '*************************'
        self.role = 'leader'
        self.nextIndex = {}
        self.matchIndex = {}
        for peer in self.peers:
            self.nextIndex[peer] = len(self.log) + 1
            self.matchIndex[peer] = 0
        nodes = []
        nodes.append(self._formFriendlyName(self.id))
        for peer in self.peers:
            nodes.append(self._formFriendlyName(peer))
        self.initialState[SERVER_NODE_GROUP_NAME] = nodes
        _uuid = uuid.uuid1()
        newAppendLogEntry = LogEntry(self.currentTerm, self.initialState, BaseMessage.LocalMessageAddress, _uuid)
        self.log.append(newAppendLogEntry)
        self.appendEntries()

    def _formFriendlyName(self, id):
        return 'Server '+ str(id)


    def appendEntries(self):
        if DEBUG:
            print 'Server appendEntries Method ', self.id, " ", self.currentTerm
        receipts = self.peers[:]
        while 1:
            receipts = self.peers[:]
            if self.during_change != 0:
                for peer in receipts:
                    if peer not in self.nextIndex:
                        self.nextIndex[peer] = len(self.log) + 1
                        self.matchIndex[peer] = 0
            for peer in receipts:
                if len(self.log) >= self.nextIndex[peer]:
                    prevLogIndex = self.nextIndex[peer] - 1
                    if prevLogIndex != 0:
                        prevLogTerm = self.log[prevLogIndex-1].term
                    else:
                        prevLogTerm = 0
                    entries = [self.log[self.nextIndex[peer]-1]]
                else:
                    entries = []
                    prevLogIndex = len(self.log)
                    if prevLogIndex != 0:
                        prevLogTerm = self.log[prevLogIndex-1].term
                    else:
                        prevLogTerm = 0

                msg = AppendEntriesMessage(self.id, peer, self.currentTerm, entries, self.commitIndex, prevLogIndex, prevLogTerm)
                data = pickle.dumps(msg)
                sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                sock.sendto(data, ("", self.addressbook[peer]))
            time.sleep(0.5)

    def stepDown(self):
        logger.info('Server stepDown Method')
        if self.role == 'candidate':
            print 'candidate step down when higher term and becomes follower', self.id, " ", self.currentTerm
            self.election.kill()
            self.last_update = time.time()
            self.role = 'follower'
        elif self.role == 'leader':
            self.leader_state.kill()
            self.follower_state = KThread(target = self.follower, args = ())
            self.follower_state.start()

    def load(self):
        print 'Server load config Method ', self.id
        initial_running = [1,2,3]

        try:
            with open(self.configFile) as f:
                serverConfig = pickle.load(f)
        except Exception as e:
            if self.id not in initial_running:
                serverConfig = ServerConfig(100, 0, -1, [], [])
            else:
                initial_running.remove(self.id)
                serverConfig = ServerConfig(100, 0, -1, [], initial_running)

        self.groupInfo = serverConfig.groupInfo
        self.currentTerm = serverConfig.currentTerm
        self.votedFor = serverConfig.votedFor
        self.log = serverConfig.log
        self.peers = serverConfig.peers
        self.majority = (len(self.peers) + 1)/2 + 1

    def save(self):
        if DEBUG:
            print 'Server save config Method ', self.id, " ", self.currentTerm
        serverConfig = ServerConfig(self.groupInfo, self.currentTerm, self.votedFor, self.log, self.peers)
        with open(self.configFile, 'w') as f:
            pickle.dump(serverConfig, f)

    def run(self):
        if DEBUG:
            print 'Server thread run Method ', self.id, " ", self.currentTerm
        time.sleep(1)
        self.follower_state = KThread(target = self.follower, args = ())
        self.follower_state.start()




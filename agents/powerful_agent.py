import rx
import zmq
from rx import operators as ops
from zmq.auth import CURVE_ALLOW_ANY
from zmq.auth.thread import ThreadAuthenticator

from .agent import Agent
from .utils import Message


class PowerfulAgent(Agent):
    def __init__(self, *args, **kwargs):
        self.zap = None
        super().__init__(*args, **kwargs)

    def _shutdown(self, signum, frame):
        if self.zap:
            self.log.info("stopping ZMQ Authenticator ...")
            self.zap.stop()
        super()._shutdown(signum, frame)

    ####################################################################################################
    ## router/client pattern
    ####################################################################################################

    def create_router(self, address, options=None):
        if options is None:
            options = {}
        router = self.bind_socket(zmq.ROUTER, options, address)

        def route(x):
            source, dest = x[0:2]
            router.send([dest, source] + x[2:])

        router.observable.subscribe(route)
        return router

    def create_client(self, address, options=None):
        if options is None:
            options = {}
        if zmq.IDENTITY not in options:
            options[zmq.IDENTITY] = self.name.encode("utf-8")
        dealer = self.connect_socket(zmq.DEALER, options, address)
        return dealer.update(
            {"observable": dealer.observable.pipe(ops.map(Message.decode))}
        )

    ####################################################################################################
    ## notifications pattern
    ####################################################################################################

    def create_notification_broker(self, pub_address, sub_address, options=None):
        """Starts a pub-sub notifications broker

        Args:
            pub_address (str): agents publish to this address to notify other agents
            sub_address (str): agents listen on this address for notifications

        Returns:
            connections (pub, sub)
        """
        if options is None:
            options = {}
        xpub = self.bind_socket(zmq.XPUB, options, sub_address)
        xsub = self.bind_socket(zmq.XSUB, options, pub_address)
        xsub.observable.subscribe(lambda x: xpub.send(x))
        xpub.observable.subscribe(lambda x: xsub.send(x))
        return xsub, xpub

    def create_notification_client(
        self, pub_address, sub_address, options=None, topics=""
    ):
        """Creates 2 connections (pub, sub) to a notifications broker

        Args:
            pub_address (str): publish to this address to notify other agents
            sub_address (str): listen on this address for notifications

        Returns:
            connections (pub, sub)
        """
        if options is None:
            options = {}
        pub = self.connect_socket(zmq.PUB, options, pub_address)
        sub = self.connect_socket(zmq.SUB, options, sub_address)
        sub.socket.subscribe(topics)
        return pub, sub.update(
            {"observable": sub.observable.pipe(ops.map(Message.decode))}
        )

    ####################################################################################################
    ## authentication
    ####################################################################################################

    def start_authenticator(
        self, domain="*", whitelist=None, blacklist=None, certificates_path=None
    ):
        """Starts ZAP Authenticator in thread

        configure_curve must be called every time certificates are added or removed, in order to update the Authenticator’s state

        Args:
            certificates_path (str): path to client public keys to allow
            whitelist (list[str]): ip addresses to whitelist
            domain: (str): domain to apply authentication
        """
        certificates_path = certificates_path if certificates_path else CURVE_ALLOW_ANY
        self.zap = ThreadAuthenticator(self.zmq_context, log=self.log)
        self.zap.start()
        if whitelist is not None:
            self.zap.allow(*whitelist)
        elif blacklist is not None:
            self.zap.deny(*blacklist)
        else:
            self.zap.allow()
        self.zap.configure_curve(domain=domain, location=certificates_path)
        return self.zap

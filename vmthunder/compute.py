#!/usr/bin/env python

import time
import os
import sys
import threading
import traceback
from oslo.config import cfg

from vmthunder import blockservice
from vmthunder.drivers import fcg
from vmthunder.drivers import volt
from vmthunder.drivers import iscsi
from vmthunder.image import LocalImage
from vmthunder.image import BlockDeviceImage
from vmthunder.utils.singleton import singleton

from vmthunder.openstack.common import log as logging


host_opts = [
    cfg.StrOpt('host_ip',
               default='192.168.137.101',
               help='localhost ip provide VMThunder service'),
    cfg.StrOpt('host_port',
               default='8001',
               help='localhost port to provide VMThunder service'),
    cfg.IntOpt('heartbeat_interval',
               default=20,
               help='localhost heartbeat interval'),
]
compute_opts = [
    cfg.IntOpt('thread_pool_size',
               default=100,
               help='The count of work threads'),
]

CONF = cfg.CONF
CONF.register_opts(host_opts)
CONF.register_opts(compute_opts)


LOG = logging.getLogger(__name__)


class Compute(object):

    def __init__(self):
        pass

    def create(self, instance_name, image_name, image_connections, snapshot):
        return NotImplementedError()

    def destroy(self, instance_name):
        return NotImplementedError()

    def list(self):
        return NotImplementedError()

@singleton
class VMThunderCompute(Compute):

    def __init__(self, openstack_compatible=True):
        LOG.info("VMThunder: start to create a VMThunder Compute_node")
        self.openstack_compatible = openstack_compatible
        self.images = {}
        self.instance_names = {}
        self.lock = threading.Lock()
        self.image_target_id = 0

        if self.openstack_compatible:
            config_files = ['/etc/nova/nova.conf', '/etc/vmthunder/vmthunder.conf']
        else:
            config_files = ['/etc/vmthunder/vmthunder.conf']
        CONF(sys.argv[1:], project='vmthunder', default_config_files=config_files)

        logging.setup('vmthunder')
        if not fcg.is_valid():
            fcg.create_group()

        self.heartbeat_event = threading.Event()
        self.heartbeat_thread = threading.Thread(target=self.heartbeat_clock)
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()
        LOG.info("VMThunder: create a VMThunder Compute_node completed")

    def __del__(self):
        self.heartbeat_event.set()

    def heartbeat_clock(self):
        while not self.heartbeat_event.wait(CONF.heartbeat_interval):
            try:
                self.heartbeat()
            except Exception, e:
                LOG.error("VMThudner: heartbeat failed due to %s" % e)
                LOG.error("VMThunder: traceback is : %s" % traceback.print_exc())
        LOG.debug("VMThunder: stop heartbeat timer")

    def heartbeat(self):
        with self.lock:
            self._heartbeat()

    def _heartbeat(self):
        LOG.debug("VMThunder: heartbeat start @ %s" % time.asctime())
        for name in self.images.keys():
            if not self.images[name].has_instance:
                if self.images[name].destroy_image():
                    del self.images[name]
        info = volt.heartbeat()
        for name in self.images.keys():
            for image in info:
                if self.images[name].base_image.peer_id == image['peer_id']:
                    self.images[name].adjust_for_heartbeat(image['parents'])
                    break
        LOG.debug("VMThunder: heartbeat end @ %s" % time.asctime())

    def create(self, instance_name, image_name, image_connections, snapshot=None):
        """
        :param instance_name: string
        :param image_name: string. It is 'iqn', likes "iqn.2010-10.org.openstack:vol_id"
        :param image_connections: list or tuple or single dict, like ({},..) or [{},..] or {}
                                  and each dict make of {'target_portal':..,'target_iqn':..,'target_lun':.., ..}
        :param snapshot: snapshot_connection or snapshot_dev
        """
        # multiple roots for creating
        with self.lock:
            return self._create(instance_name, image_name, image_connections, snapshot)

    def _create(self, instance_name, image_name, image_connections, snapshot):
        LOG.debug("VMThunder: Begin! ----- PID = %s" % os.getpid())
        print "VMThunder: begin!"
        # Just support for openstack
        if not image_name.startswith("volume-"):
            image_name = "volume-" + image_name
        # for multi image server
        if isinstance(image_connections, tuple) or isinstance(image_connections, list):
            image_connections = list(image_connections)
        else:
            image_connections = [image_connections]
        #with self.lock:
        if self.instance_names.has_key(instance_name):
            LOG.debug("VMThunder: the instance_name \'%s\' already exists!" % (instance_name))
            return ''
        else:
        #TODO: try: exception
            self.instance_names[instance_name] = image_name
        LOG.debug("VMThunder: create VM started, instance_name = %s, image_name = %s" % (instance_name, image_name))
        if not self.images.has_key(image_name):
            LOG.debug("VMThunder: now need to create image first!")
            if not self.openstack_compatible:
                self.images[image_name] = LocalImage(image_name, image_connections)
            else:
                self.images[image_name] = BlockDeviceImage(image_name, image_connections)
        self.images[image_name].has_instance = True
        print "VMThunder: middle!"
        instance_path = self.images[image_name].create_instance(instance_name, snapshot)
        LOG.debug("VMThunder: create VM completed, instance_name = %s, image_name = %s, instance_path = %s" % (instance_name, image_name, instance_path))
        # instance_path is like '/dev/mapper/snapshot_vm1' in local deployment
        print "VMThunder: end!  instance_path = ", instance_path
        return instance_path

    def destroy(self, instance_name):
        with self.lock:
            return self._destroy(instance_name)

    def _destroy(self, instance_name):
        LOG.debug("VMThunder: destroy VM started, instance_name = %s" % (instance_name))
        if not self.instance_names.has_key(instance_name):
            LOG.debug("VMThunder: the instance_name \'%s\' does not exist!" % (instance_name))
            return False
        else:
            image_name = self.instance_names[instance_name]
            if self.images[image_name].destroy_instance(instance_name):
                #with self.lock:
                del self.instance_names[instance_name]
            LOG.debug("VMThunder: destroy VM completed, instance_name = %s" % (instance_name))
            return True

    def list(self):
        instance_list = []
        for instance_name, image_name in self.instance_names.items():
            instance_list.append(instance_name+':'+image_name)
        return instance_list

    def create_image_target(self, image_name, file_path, loop_dev, iqn_prefix):
        LOG.debug("VMThunder: Image Target Service: create image target started! image_name = %s, "
                  "file_path = %s" % (image_name, file_path))
        if not image_name.startswith("volume-"):
            image_name = "volume-" + image_name
        blockservice.unlinkloop(loop_dev)
        blockservice.linkloop(loop_dev, file_path)
        self.image_target_id = iscsi.create_iscsi_target(iqn_prefix + image_name, loop_dev)
        LOG.debug("VMThunder: Image Target Service: create image target completed! image_target_id = %s"
                  % self.image_target_id )
        return self.image_target_id

    def destroy_image_target(self, image_name):
        LOG.debug("VMThunder: Image Target Service: remove image target started! image_name = %s" % image_name)
        if not image_name.startswith("volume-"):
            image_name = "volume-" + image_name
        nothing = iscsi.remove_iscsi_target(self.image_target_id, 1, image_name, image_name)
        LOG.debug("VMThunder: Image Target Service: remove image target completed!")
        return nothing

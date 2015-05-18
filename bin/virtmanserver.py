#!/usr/bin/env python

from SimpleXMLRPCServer import SimpleXMLRPCServer
from SimpleXMLRPCServer import SimpleXMLRPCRequestHandler

from virtman.compute import Virtman
from virtman import imageservice


class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/RPC2',)


class SimpleCompute(object):

    @staticmethod
    def create(instance_name, image_name, image_connection, snapshot_dev):
        cn = Virtman(openstack_compatible=False)
        return cn.create(instance_name, image_name, image_connection,
                         snapshot_dev)

    @staticmethod
    def destroy(instance_name):
        cn = Virtman(openstack_compatible=False)
        return cn.destroy(instance_name)

    @staticmethod
    def list():
        cn = Virtman(openstack_compatible=False)
        return cn.list()

    @staticmethod
    def create_image_target(image_name, file_path, loop_dev, iqn_prefix):
        return imageservice.create_image_target(image_name, file_path, loop_dev,
                                                iqn_prefix)

    @staticmethod
    def destroy_image_target(image_name):
        return imageservice.destroy_image_target(image_name)

    @staticmethod
    def list_image_target():
        return imageservice.list_image_target()

if __name__ == '__main__':
    server = SimpleXMLRPCServer(("0.0.0.0", 7774), RequestHandler,
                                allow_none=True)
    server.register_introspection_functions()
    server.register_instance(SimpleCompute)
    print "Virtman Server Run ..."
    server.serve_forever()

__FILENAME__ = osm-slurp
from sys import stdin
from math import hypot, ceil

from shapely.geometry import Polygon

from Skeletron import network_multiline, multiline_centerline, multiline_polygon
from Skeletron.util import simplify_line, polygon_rings
from Skeletron.input import ParserOSM
from Skeletron.draw import Canvas

p = ParserOSM()
g = p.parse(stdin)

print sorted(g.keys())

network = g[(u'Lakeside Drive', u'secondary')]

if not network.edges():
    exit(1)

lines = network_multiline(network)
poly = multiline_polygon(lines)
center = multiline_centerline(lines)

# draw

points = [network.node[id]['point'] for id in network.nodes()]
xs, ys = map(None, *[(pt.x, pt.y) for pt in points])

xmin, ymin, xmax, ymax = min(xs), min(ys), max(xs), max(ys)

canvas = Canvas(900, 600)
canvas.fit(xmin - 50, ymax + 50, xmax + 50, ymin - 50)

for geom in center.geoms:
    line = list(geom.coords)

    canvas.line(line, stroke=(1, 1, 1), width=10)
    for (x, y) in line:
        canvas.dot(x, y, fill=(1, 1, 1), size=16)

    canvas.line(line, stroke=(1, .6, .4), width=6)
    for (x, y) in line:
        canvas.dot(x, y, fill=(1, .6, .4), size=12)

for ring in polygon_rings(poly):
    canvas.line(list(ring.coords), stroke=(.9, .9, .9))

for (a, b) in network.edges():
    pt1, pt2 = network.node[a]['point'], network.node[b]['point']
    line = [(pt1.x, pt1.y), (pt2.x, pt2.y)]
    canvas.line(line, stroke=(0, 0, 0))

for point in points:
    canvas.dot(point.x, point.y, fill=(0, 0, 0))

canvas.save('look.png')

########NEW FILE########
__FILENAME__ = osm-to-json
from sys import stdin, argv
from math import hypot, ceil
from json import dump

from shapely.geometry import Polygon, MultiLineString

from Skeletron import network_multiline, multiline_polygon, polygon_skeleton, skeleton_routes
from Skeletron.input import ParserOSM, merc

p = ParserOSM()
g = p.parse(stdin)

output = dict(type='FeatureCollection', features=[])

for key in g:
    print key
    network = g[key]
    
    if not network.edges():
        continue
    
    lines = network_multiline(network)
    poly = multiline_polygon(lines)
    skeleton = polygon_skeleton(poly)
    routes = skeleton_routes(skeleton)
    
    if not routes:
        continue
    
    coords = [[merc(*point, inverse=True) for point in route] for route in routes]
    geometry = MultiLineString(coords).__geo_interface__
    properties = dict(name=key[0], highway=key[1])
    
    feature = dict(geometry=geometry, properties=properties)
    output['features'].append(feature)

dump(output, open(argv[2], 'w'))

########NEW FILE########
__FILENAME__ = draw
from math import pi

from cairo import Context, ImageSurface, FORMAT_RGB24, LINE_CAP_ROUND

class Canvas:

    def __init__(self, width, height):
        self.xform = lambda x, y: (x, y)
    
        self.img = ImageSurface(FORMAT_RGB24, width, height)
        self.ctx = Context(self.img)
        
        self.ctx.move_to(0, 0)
        self.ctx.line_to(width, 0)
        self.ctx.line_to(width, height)
        self.ctx.line_to(0, height)
        self.ctx.line_to(0, 0)
        
        self.ctx.set_source_rgb(1, 1, 1)
        self.ctx.fill()
        
        self.width = width
        self.height = height
    
    def fit(self, left, top, right, bottom):
        xoff = left
        yoff = top
        
        xscale = self.width / float(right - left)
        yscale = self.height / float(bottom - top)
        
        if abs(xscale) > abs(yscale):
            xscale *= abs(yscale) / abs(xscale)
        
        elif abs(xscale) < abs(yscale):
            yscale *= abs(xscale) / abs(yscale)

        self.xform = lambda x, y: ((x - xoff) * xscale, (y - yoff) * yscale)
    
    def dot(self, x, y, size=4, fill=(.5, .5, .5)):
        x, y = self.xform(x, y)

        self.ctx.arc(x, y, size/2., 0, 2*pi)
        self.ctx.set_source_rgb(*fill)
        self.ctx.fill()
    
    def line(self, points, stroke=(.5, .5, .5), width=1):
        self.ctx.move_to(*self.xform(*points[0]))
        
        for (x, y) in points[1:]:
            self.ctx.line_to(*self.xform(x, y))
        
        self.ctx.set_source_rgb(*stroke)
        self.ctx.set_line_cap(LINE_CAP_ROUND)
        self.ctx.set_line_width(width)
        self.ctx.stroke()
    
    def save(self, filename):
        self.img.write_to_png(filename)

########NEW FILE########
__FILENAME__ = input
from copy import deepcopy
from xml.parsers.expat import ParserCreate
from logging import debug

def name_key(tags):
    """ Convert way tags to name keys.
    
        Used by ParserOSM.parse().
    """
    if 'name' not in tags:
        return None
    
    if not tags['name']:
        return None
    
    return (tags['name'], )

def name_highway_key(tags):
    """ Convert way tags to name, highway keys.
    
        Used by ParserOSM.parse().
    """
    if 'name' not in tags:
        return None

    if 'highway' not in tags:
        return None
    
    if not tags['name'] or not tags['highway']:
        return None
    
    return tags['name'], tags['highway']

def network_ref_modifier_key(tags):
    """ Convert relation tags to network, ref keys.
    
        Used by ParserOSM.parse().
    """
    if 'network' not in tags:
        return None

    if 'ref' not in tags:
        return None
    
    if not tags['network'] or not tags['ref']:
        return None
    
    return tags['network'], tags['ref'], tags.get('modifier', '')

def name_highway_ref_key(tags):
    """ Convert way tags to name, highway, ref keys.
    
        Used by ParserOSM.parse().
    """
    if tags.get('highway', None) and tags['highway'].endswith('_link'):
        return tags.get('name', None), tags['highway'][:-5], tags.get('ref', None)
    
    return tags.get('name', None), tags.get('highway', None), tags.get('ref', None)

def parse_street_waynodes(input, use_highway):
    """ Parse OSM XML input, return ways and nodes for waynode_networks().
    
        Uses name_highway_key() for way keys, ignores relations.
    """
    way_key = use_highway and name_highway_key or name_key
    rels, ways, nodes = ParserOSM().parse(input, way_key=way_key)
    
    return ways, nodes

def parse_route_relation_waynodes(input, merge_highways):
    """ Parse OSM XML input, return ways and nodes for waynode_networks().
    
        Uses network_ref_modifier_key() for relation keys, converts way keys to fit.

        Assumes correctly-tagged route relations:
            http://wiki.openstreetmap.org/wiki/Relation:route
    """
    rels, ways, nodes = ParserOSM().parse(input, way_key=name_highway_ref_key, rel_key=network_ref_modifier_key)
    
    #
    # Collapse subrelations to surface ways.
    #
    
    changing = True

    while changing:
        changing = False
    
        for rel in rels.values():
            parts = rel['parts']

            for (index, part) in enumerate(parts):
                if part.startswith('rel:'):
                    rel_id = part[4:]
                
                    if rel_id in rels:
                        # there's a matching subrelation, so pull all
                        # its members up into this one looking for ways.

                        parts[index:index+1] = rels[rel_id]['parts']
                        del rels[rel_id]
                        changing = True
                    else:
                        # no matching relation means drop it on the floor.
                        parts[index:index+1] = []
                        changing = True
            
                elif part.startswith('way:'):
                    # good, we want these
                    pass
            
                else:
                    # not sure what this is, can't be good.
                    parts[index:index+1] = []
                    changing = True
            
            if changing:
                # rels was modified, try another round
                break
    
    #
    # Apply relation keys to ways.
    #
    
    rel_ways = dict()
    
    highways = dict(motorway=9, trunk=8, primary=7, secondary=6, tertiary=5)
    net_refs = dict()
    
    for rel in rels.values():
        for part in rel['parts']:
            # we know from above that they're all "way:".
            way_id = part[4:]
            
            # add the route relation key to the way
            rel_way = deepcopy(ways[way_id])
            way_name, way_hwy, way_ref = rel_way['key']
            rel_net, rel_ref, rel_mod = rel['key']
            
            if merge_highways == 'yes':
                rel_way['key'] = rel_net, rel_ref, rel_mod

            elif merge_highways == 'largest':
                rel_way['key'] = rel_net, rel_ref, rel_mod
                big_hwy = net_refs.get((rel_net, rel_ref), None)
                
                if big_hwy is None or (highways.get(way_hwy, 0) > highways.get(big_hwy, 0)):
                    #
                    # Either we've not yet seen this network/ref combination or
                    # the current highway value is larger than the previously
                    # seen largest one. Make a note of it for later.
                    #
                    net_refs[(rel_net, rel_ref, rel_mod)] = way_hwy

            else:
                rel_way['key'] = rel_net, rel_ref, rel_mod, way_hwy
            
            rel_ways[len(rel_ways)] = rel_way
    
    debug('%d rel_ways, %d nodes' % (len(rel_ways), len(nodes)))
    
    if merge_highways == 'largest':
        #
        # Run through the list again, assigning largest highway
        # values from net_refs dictionary to each way key.
        #
        for (key, rel_way) in rel_ways.items():
            network, ref, modifier = rel_way['key']
            highway = net_refs[(network, ref, modifier)]
            rel_ways[key]['key'] = network, ref, modifier, highway
    
    debug('%d rel_ways, %d nodes' % (len(rel_ways), len(nodes)))
    
    return rel_ways, nodes

class ParserOSM:

    nodes = None
    ways = None
    rels = None
    way = None
    rel = None
    way_key = None
    rel_key = None

    def __init__(self):
        self.p = ParserCreate()
        self.p.StartElementHandler = self.start_element
        self.p.EndElementHandler = self.end_element
        #self.p.CharacterDataHandler = char_data
    
    def parse(self, input, way_key=lambda tags: None, rel_key=lambda tags: None):
        """ Given a file-like stream of OSM XML data, return dictionaries of ways and nodes.
        
            Keys are generated from way tags based on the way_key and ref_key arguments.
        """
        self.nodes = dict()
        self.ways = dict()
        self.rels = dict()
        self.way_key = way_key
        self.rel_key = rel_key
        self.p.ParseFile(input)
        return self.rels, self.ways, self.nodes
    
    def start_element(self, name, attrs):
        if name == 'node':
            self.add_node(attrs['id'], float(attrs['lat']), float(attrs['lon']))
        
        elif name == 'way':
            self.add_way(attrs['id'])
        
        elif name == 'tag' and self.way:
            self.tag_way(attrs['k'], attrs['v'])
        
        elif name == 'nd' and attrs['ref'] in self.nodes and self.way:
            self.extend_way(attrs['ref'])
        
        elif name == 'relation':
            self.add_relation(attrs['id'])
        
        elif name == 'tag' and self.rel:
            self.tag_relation(attrs['k'], attrs['v'])
        
        elif name == 'member':
            if attrs['type'] == 'way' and attrs['ref'] in self.ways and self.rel:
                self.extend_relation(attrs['ref'], 'way')
            
            elif attrs['type'] == 'relation' and self.rel:
                self.extend_relation(attrs['ref'], 'rel')
    
    def end_element(self, name):
        if name == 'way':
            self.end_way()

        elif name == 'relation':
            self.end_relation()

    def add_node(self, id, lat, lon):
        self.nodes[id] = lat, lon
    
    def add_way(self, id):
        self.way = id
        self.ways[id] = dict(nodes=[], tags=dict(), key=None)
    
    def tag_way(self, key, value):
        way = self.ways[self.way]
        way['tags'][key] = value
    
    def extend_way(self, id):
        way = self.ways[self.way]
        way['nodes'].append(id)
    
    def end_way(self):
        way = self.ways[self.way]
        key = self.way_key(way['tags'])
        
        if key:
            way['key'] = key
            del way['tags']

        else:
            del self.ways[self.way]
        
        self.way = None
    
    def add_relation(self, id):
        self.rel = id
        self.rels[id] = dict(parts=[], tags=dict(), key=None)
    
    def tag_relation(self, key, value):
        rel = self.rels[self.rel]
        rel['tags'][key] = value
    
    def extend_relation(self, id, member):
        rel = self.rels[self.rel]
        rel['parts'].append('%(member)s:%(id)s' % locals())
    
    def end_relation(self):
        rel = self.rels[self.rel]
        key = self.rel_key(rel['tags'])
        
        if key:
            rel['key'] = key
            del rel['tags']

        else:
            del self.rels[self.rel]
        
        self.rel = None

########NEW FILE########
__FILENAME__ = output
from pickle import dumps as pickleit
from tempfile import mkstemp
from os import write, close
from json import dumps

import logging

from shapely.geometry import LineString, MultiLineString, asShape

from . import multigeom_centerline, mercator, _GraphRoutesOvertime, projected_multigeometry
from .util import zoom_buffer

def generalize_geojson_feature(feature, width, zoom):
    ''' Run one GeoJSON feature through Skeletron and return it.
    
        If generalization fails, return False.
    '''
    prop = dict([(k.lower(), v) for (k, v) in feature['properties'].items()])
    name = prop.get('name', prop.get('id', prop.get('gid', prop.get('fid', None))))
    geom = asShape(feature['geometry'])

    buffer = zoom_buffer(width, zoom)
    kwargs = dict(buffer=buffer, density=buffer/2, min_length=8*buffer, min_area=(buffer**2)/4)
    
    logging.info('Generalizing %s, %d wkb, %.1f buffer' % (dumps(name), len(geom.wkb), buffer))
    
    multigeom = projected_multigeometry(geom)
    generalized = generalized_multiline(multigeom, **kwargs)
    
    if generalized is None:
        return False
    
    feature['geometry'] = generalized.__geo_interface__
    
    return feature

def generalize_geometry(geometry, width, zoom):
    ''' Run one geometry through Skeletron and return it.
    
        If generalization fails, return False.
    '''
    buffer = zoom_buffer(width, zoom)
    kwargs = dict(buffer=buffer, density=buffer/2, min_length=8*buffer, min_area=(buffer**2)/4)
    
    logging.debug('Generalizing %s, %d wkb, %.1f buffer' % (geometry.type, len(geometry.wkb), buffer))
    
    multigeom = projected_multigeometry(geometry)
    generalized = generalized_multiline(multigeom, **kwargs)
    
    if generalized is None:
        return False
    
    return generalized

def multilines_geojson(multilines, key_properties, buffer, density, min_length, min_area):
    """
    """
    geojson = dict(type='FeatureCollection', features=[])

    for (key, multiline) in sorted(multilines.items()):
        
        logging.info('%s...' % ', '.join([(p or '').encode('ascii', 'ignore') for p in key]))
        
        try:
            centerline = multigeom_centerline(multiline, buffer, density, min_length, min_area)
        
        except _GraphRoutesOvertime, e:
            #
            # Catch overtimes here because they seem to affect larger networks
            # and therefore most or all of a complex multiline. We'll keep the
            # key and a pickled copy of the offending graph.
            #
            logging.error('Graph routes went overtime')
            
            handle, fname = mkstemp(dir='.', prefix='graph-overtime-', suffix='.txt')
            write(handle, repr(key) + '\n' + pickleit(e.graph))
            close(handle)
            continue
        
        if not centerline:
            continue
        
        for geom in centerline.geoms:
            coords = [mercator(*point, inverse=True) for point in geom.coords]
            geometry = LineString(coords).__geo_interface__
            feature = dict(geometry=geometry, properties=key_properties(key))

            geojson['features'].append(feature)

    return geojson

def generalized_multiline(multiline, buffer, density, min_length, min_area):
    '''
    '''
    try:
        centerline = multigeom_centerline(multiline, buffer, density, min_length, min_area)
    
    except Exception, e:
        raise
        logging.error(e)
        return None
    
    if not centerline:
        return None
        
    coords = [[mercator(x, y, inverse=True) for (x, y) in line.coords] for line in centerline]
    geographic = MultiLineString(coords)
    
    return geographic

########NEW FILE########
__FILENAME__ = util
from sys import stdin, stdout
from math import hypot, ceil, sqrt, pi
from base64 import b64encode, b64decode
from json import loads as json_decode
from json import dumps as json_encode
from cPickle import loads as unpickle
from cPickle import dumps as pickle
from os.path import splitext
from gzip import GzipFile
from bz2 import BZ2File

from shapely.geometry import Polygon
from shapely.wkb import loads as wkb_decode

def zoom_buffer(width_px, zoom):
    '''
    '''
    zoom_pixels = 2**(zoom + 8)
    earth_width_meters = 2 * pi * 6378137
    meters_per_pixel = earth_width_meters / zoom_pixels
    buffer_meters = meters_per_pixel * width_px / 2
    
    return buffer_meters

def cascaded_union(polys):
    '''
    '''
    if len(polys) == 2:
        return polys[0].union(polys[1])

    if len(polys) == 1:
        return polys[0]
    
    if len(polys) == 0:
        return None
    
    half = len(polys) / 2
    poly1 = cascaded_union(polys[:half])
    poly2 = cascaded_union(polys[half:])
    
    return poly1.union(poly2)

def point_distance(a, b):
    '''
    '''
    try:
        return a.distance(b)

    except ValueError, e:
        if str(e) != 'Prepared geometries cannot be operated on':
            raise
        
        # Shapely sometimes throws this exception, for reasons unclear to me.
        return hypot(a.x - b.x, a.y - b.y)
    
def simplify_line_vw(points, small_area=100):
    """ Simplify a line of points using V-W down to the given area.
    """
    while len(points) > 3:
        
        # For each coordinate that forms the apex of a two-segment
        # triangle, find the area of that triangle and put it into a list
        # along with the index, ordered from smallest to largest.
    
        popped, preserved = set(), set()
        
        triples = zip(points[:-2], points[1:-1], points[2:])
        triangles = [Polygon((p1, p2, p3)) for (p1, p2, p3) in triples]
        areas = [(triangle.area, index) for (index, triangle) in enumerate(triangles)]
        
        # Reduce any segments that makes a triangle whose area is below
        # the minimum threshold, starting with the smallest and working up.
        # Mark segments to be preserved until the next iteration.

        for (area, index) in sorted(areas):
            if area > small_area:
                # nothing more can be removed on this iteration
                break
            
            if (index + 1) in preserved:
                # current index is too close to a previously-preserved one
                continue
            
            preserved.add(index)
            popped.add(index + 1)
            preserved.add(index + 2)
        
        if not popped:
            # nothing was removed so we are done
            break
        
        # reduce the line, then try again
        points = [point for (index, point) in enumerate(points) if index not in popped]
    
    return list(points)

def simplify_line_dp(pts, tolerance):
    """ Pure-Python Douglas-Peucker line simplification/generalization
        
        this code was written by Schuyler Erle <schuyler@nocat.net> and is
          made available in the public domain.
        
        the code was ported from a freely-licensed example at
          http://www.3dsoftware.com/Cartography/Programming/PolyLineReduction/
        
        the original page is no longer available, but is mirrored at
          http://www.mappinghacks.com/code/PolyLineReduction/
    """
    anchor  = 0
    floater = len(pts) - 1
    stack   = []
    keep    = set()

    stack.append((anchor, floater))  
    while stack:
        anchor, floater = stack.pop()
      
        # initialize line segment
        if pts[floater] != pts[anchor]:
            anchorX = float(pts[floater][0] - pts[anchor][0])
            anchorY = float(pts[floater][1] - pts[anchor][1])
            seg_len = sqrt(anchorX ** 2 + anchorY ** 2)
            # get the unit vector
            anchorX /= seg_len
            anchorY /= seg_len
        else:
            anchorX = anchorY = seg_len = 0.0
    
        # inner loop:
        max_dist = 0.0
        farthest = anchor + 1
        for i in range(anchor + 1, floater):
            dist_to_seg = 0.0
            # compare to anchor
            vecX = float(pts[i][0] - pts[anchor][0])
            vecY = float(pts[i][1] - pts[anchor][1])
            seg_len = sqrt( vecX ** 2 + vecY ** 2 )
            # dot product:
            proj = vecX * anchorX + vecY * anchorY
            if proj < 0.0:
                dist_to_seg = seg_len
            else: 
                # compare to floater
                vecX = float(pts[i][0] - pts[floater][0])
                vecY = float(pts[i][1] - pts[floater][1])
                seg_len = sqrt( vecX ** 2 + vecY ** 2 )
                # dot product:
                proj = vecX * (-anchorX) + vecY * (-anchorY)
                if proj < 0.0:
                    dist_to_seg = seg_len
                else:  # calculate perpendicular distance to line (pythagorean theorem):
                    dist_to_seg = sqrt(abs(seg_len ** 2 - proj ** 2))
                if max_dist < dist_to_seg:
                    max_dist = dist_to_seg
                    farthest = i

        if max_dist <= tolerance: # use line segment
            keep.add(anchor)
            keep.add(floater)
        else:
            stack.append((anchor, farthest))
            stack.append((farthest, floater))

    keep = list(keep)
    keep.sort()
    return [pts[i] for i in keep]

def densify_line(points, distance):
    """ Densify a line of points using the given distance.
    """
    coords = [points[0]]
    
    for curr_coord in list(points)[1:]:
        prev_coord = coords[-1]
    
        dx, dy = curr_coord[0] - prev_coord[0], curr_coord[1] - prev_coord[1]
        steps = ceil(hypot(dx, dy) / distance)
        count = int(steps)
        
        while count:
            prev_coord = prev_coord[0] + dx/steps, prev_coord[1] + dy/steps
            coords.append(prev_coord)
            count -= 1
    
    return coords

def polygon_rings(polygon):
    """ Given a buffer polygon, return a series of point rings.
    
        Return a list of interiors and exteriors all together.
    """
    if polygon.type == 'Polygon':
        return [polygon.exterior] + list(polygon.interiors)
    
    rings = []
    
    for geom in polygon.geoms:
        rings.append(geom.exterior)
        rings.extend(list(geom.interiors))
    
    return rings

def open_file(name, mode='r'):
    """
    """
    if name == '-' and mode == 'r':
        return stdin

    if name == '-' and mode == 'w':
        return stdout
    
    base, ext = splitext(name)
    
    if ext == '.bz2':
        return BZ2File(name, mode)

    if ext == '.gz':
        return GzipFile(name, mode)

    return open(name, mode)

def hadoop_feature_line(id, properties, geometry):
    ''' Convert portions of a GeoJSON feature to a single line of text.
    
        Allows Hadoop to stream features from the mapper to the reducer.
        See also skeletron-hadoop-mapper.py and skeletron-hadoop-reducer.py.
    '''
    line = [
        json_encode(id),
        ' ',
        b64encode(pickle(sorted(list(properties.items())))),
        '\t',
        b64encode(geometry.wkb)
        ]
    
    return ''.join(line)

def hadoop_line_features(line):
    ''' Convert a correctly-formatted line of text to a list of GeoJSON features.
    
        Allows Hadoop to stream features from the mapper to the reducer.
        See also skeletron-hadoop-mapper.py and skeletron-hadoop-reducer.py.
    '''
    id, prop, geom = line.split()
    
    id = json_decode(id)
    properties = dict(unpickle(b64decode(prop)))
    geometry = wkb_decode(b64decode(geom))
    
    parts = geometry.geoms if hasattr(geometry, 'geoms') else [geometry]
    
    return [dict(type='Feature', id=id, properties=properties,
                 geometry=part.__geo_interface__)
            for part
            in parts
            if hasattr(part, '__geo_interface__')]

########NEW FILE########
__FILENAME__ = skeletron-generalize
#!/usr/bin/env python
from json import load, JSONEncoder
from optparse import OptionParser
from itertools import repeat
from re import compile
import logging

from Skeletron.output import generalize_geojson_feature

float_pat = compile(r'^-?\d+\.\d+(e-?\d+)?$')
charfloat_pat = compile(r'^[\[,\,]-?\d+\.\d+(e-?\d+)?$')
earth_radius = 6378137

optparser = OptionParser(usage="""%prog [options] <geojson input file> <geojson output file>

Accepts GeoJSON input and generates GeoJSON output.""")

defaults = dict(zoom=12, width=15, single=False, loglevel=logging.INFO)

optparser.set_defaults(**defaults)

optparser.add_option('-z', '--zoom', dest='zoom',
                     type='int', help='Zoom level. Default value is %s.' % repr(defaults['zoom']))

optparser.add_option('-w', '--width', dest='width',
                     type='float', help='Line width at zoom level. Default value is %s.' % repr(defaults['width']))

optparser.add_option('-s', '--single', dest='single',
                     action='store_true',
                     help='Convert multi-geometries into single geometries on output.')

optparser.add_option('-v', '--verbose', dest='loglevel',
                     action='store_const', const=logging.DEBUG,
                     help='Output extra progress information.')

optparser.add_option('-q', '--quiet', dest='loglevel',
                     action='store_const', const=logging.WARNING,
                     help='Output no progress information.')

if __name__ == '__main__':

    options, (input_file, output_file) = optparser.parse_args()

    logging.basicConfig(level=options.loglevel, format='%(levelname)08s - %(message)s')
    
    #
    # Input
    #
    
    input = load(open(input_file, 'r'))
    features = []
    
    for (index, input_feature) in enumerate(input['features']):
        try:
            feature = generalize_geojson_feature(input_feature, options.width, options.zoom)
            
            if not feature:
                continue

        except Exception, err:
            logging.error('Error on feature #%d: %s' % (index, err))

        else:
            if options.single and feature['geometry']['type'].startswith('Multi'):
                coord = [part for part in feature['geometry']['coordinates']]
                types = repeat(feature['geometry']['type'][5:])
                props = repeat(feature['properties'])
                
                features.extend([dict(type='Feature', geometry=dict(coordinates=coords, type=type), properties=prop)
                                 for (coords, type, prop) in zip(coord, types, props)])
            
            else:
                features.append(feature)
    
    #
    # Output
    #
    
    geojson = dict(type='FeatureCollection', features=filter(None, features))
    output = open(output_file, 'w')

    encoder = JSONEncoder(separators=(',', ':'))
    encoded = encoder.iterencode(geojson)
    
    for token in encoded:
        if charfloat_pat.match(token):
            # in python 2.7, we see a character followed by a float literal
            output.write(token[0] + '%.5f' % float(token[1:]))
        
        elif float_pat.match(token):
            # in python 2.6, we see a simple float literal
            output.write('%.5f' % float(token))
        
        else:
            output.write(token)

########NEW FILE########
__FILENAME__ = skeletron-hadoop-mapper
#!/usr/bin/env python
'''

Test usage:
    cat oakland-sample.json | ./skeletron-hadoop-mapper.py | sort | ./skeletron-hadoop-reducer.py > output.json
'''
from sys import stdin, stdout
from json import load, dumps
from itertools import product
from uuid import uuid1

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)08s - %(message)s')

from shapely.geometry import asShape
from Skeletron.output import generalize_geometry
from Skeletron.util import hadoop_feature_line

if __name__ == '__main__':

    geojson = load(stdin)
    pixelwidth = 20
    
    for (feature, zoom) in product(geojson['features'], (12, 13, 14, 15, 16)):

        id = str(uuid1())
        prop = feature.get('properties', {})
        geom = asShape(feature['geometry'])
    
        try:
            skeleton = generalize_geometry(geom, pixelwidth, zoom)
            bones = getattr(skeleton, 'geoms', [skeleton])
            prop.update(dict(zoomlevel=zoom, pixelwidth=pixelwidth))
            
            if not skeleton:
                logging.debug('Empty skeleton')
                continue
            
        except Exception, e:
            logging.error(str(e))
            continue
        
        if id is None:
            for (index, bone) in enumerate(bones):
                logging.info('line %d of %d from %s' % (1 + index, len(bones), dumps(prop)))
                print >> stdout, hadoop_feature_line(id, prop, bone)
        else:
            logging.info('%d-part multiline from %s' % (len(bones), dumps(prop)))
            print >> stdout, hadoop_feature_line(id, prop, skeleton)

########NEW FILE########
__FILENAME__ = skeletron-hadoop-reducer
#!/usr/bin/env python
'''

Test usage:
    cat oakland-sample.json | ./skeletron-hadoop-mapper.py | sort | ./skeletron-hadoop-reducer.py > output.json
'''
from sys import stdout, stdin
from json import loads, JSONEncoder
from re import compile

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)08s - %(message)s')

from Skeletron.util import hadoop_line_features

float_pat = compile(r'^-?\d+\.\d+(e-?\d+)?$')
charfloat_pat = compile(r'^[\[,\,]-?\d+\.\d+(e-?\d+)?$')

if __name__ == '__main__':

    features = []
    
    for line in stdin:
        try:
            features.extend(hadoop_line_features(line))
        
        except Exception, e:
            logging.error(str(e))
            continue

    geojson = dict(type='FeatureCollection', features=features)
    encoder = JSONEncoder(separators=(',', ':'))
    encoded = encoder.iterencode(geojson)
    
    for token in encoded:
        if charfloat_pat.match(token):
            # in python 2.7, we see a character followed by a float literal
            stdout.write(token[0] + '%.5f' % float(token[1:]))
        
        elif float_pat.match(token):
            # in python 2.6, we see a simple float literal
            stdout.write('%.5f' % float(token))
        
        else:
            stdout.write(token)

########NEW FILE########
__FILENAME__ = skeletron-osm-route-rels
#!/usr/bin/env python
""" Run with "--help" flag for more information.

Accepts OpenStreetMap XML input and generates GeoJSON output for routes
using the "network", "ref" and "modifier" tags to group relations.
More on route relations: http://wiki.openstreetmap.org/wiki/Relation:route
"""

from sys import argv, stdin, stdout
from itertools import combinations
from optparse import OptionParser
from csv import DictReader
from re import compile
from json import dump
from math import pi

import logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)08s - %(message)s')

from Skeletron import waynode_multilines
from Skeletron.input import parse_route_relation_waynodes
from Skeletron.output import multilines_geojson
from Skeletron.util import open_file

earth_radius = 6378137

optparser = OptionParser(usage="""%prog [options] <osm input file> <geojson output file>

Accepts OpenStreetMap XML input and generates GeoJSON output for routes
using the "network", "ref" and "modifier" tags to group relations.
More on route relations: http://wiki.openstreetmap.org/wiki/Relation:route""")

defaults = dict(zoom=12, width=15, merge_highways='no')

optparser.set_defaults(**defaults)

optparser.add_option('-z', '--zoom', dest='zoom',
                     type='int', help='Zoom level. Default value is %s.' % repr(defaults['zoom']))

optparser.add_option('-w', '--width', dest='width',
                     type='float', help='Line width at zoom level. Default value is %s.' % repr(defaults['width']))

optparser.add_option('--merge-highways', dest='merge_highways',
                     choices=('yes', 'no', 'largest'), help='Highway merging behavior: "yes" merges highway tags (e.g. collapses primary and secondary) when they share a network and ref tag, "no" keeps them separate, and "largest" merges but outputs the value of the largest highway (e.g. motorway). Default value is "%s".' % defaults['merge_highways'])

if __name__ == '__main__':
    
    options, (input_file, output_file) = optparser.parse_args()
    
    buffer = options.width / 2
    buffer *= (2 * pi * earth_radius) / (2**(options.zoom + 8))
    
    #
    # Input
    #
    
    input = open_file(input_file, 'r')
    
    ways, nodes = parse_route_relation_waynodes(input, options.merge_highways)
    multilines = waynode_multilines(ways, nodes)
    
    #
    # Output
    #
    
    kwargs = dict(buffer=buffer, density=buffer/2, min_length=8*buffer, min_area=(buffer**2)/4)
    
    if options.merge_highways == 'yes':
        def key_properties((network, ref, modifier)):
            return dict(network=network, ref=ref, modifier=modifier,
                        zoomlevel=options.zoom, pixelwidth=options.width)
    else:
        def key_properties((network, ref, modifier, highway)):
            return dict(network=network, ref=ref, modifier=modifier, highway=highway,
                        zoomlevel=options.zoom, pixelwidth=options.width)

    logging.info('Buffer: %(buffer).1f, density: %(density).1f, minimum length: %(min_length).1f, minimum area: %(min_area).1f.' % kwargs)

    geojson = multilines_geojson(multilines, key_properties, **kwargs)
    output = open_file(output_file, 'w')
    dump(geojson, output)

########NEW FILE########
__FILENAME__ = skeletron-osm-streets
#!/usr/bin/env python
""" Run with "--help" flag for more information.

Accepts OpenStreetMap XML input and generates GeoJSON output for streets
using the "name" and "highway" tags to group collections of ways.
"""

from sys import argv, stdin, stderr, stdout
from itertools import combinations
from optparse import OptionParser
from csv import DictReader
from re import compile
from json import dump
from math import pi

from StreetNames import short_street_name

from Skeletron import waynode_multilines
from Skeletron.input import parse_street_waynodes
from Skeletron.output import multilines_geojson
from Skeletron.util import open_file

earth_radius = 6378137

optparser = OptionParser(usage="""%prog [options] <osm input file> <geojson output file>

Accepts OpenStreetMap XML input and generates GeoJSON output for streets
using the "name" and "highway" tags to group collections of ways.""")

defaults = dict(zoom=12, width=10, use_highway=True)

optparser.set_defaults(**defaults)

optparser.add_option('-z', '--zoom', dest='zoom',
                     type='int', help='Zoom level. Default value is %s.' % repr(defaults['zoom']))

optparser.add_option('-w', '--width', dest='width',
                     type='float', help='Line width at zoom level. Default value is %s.' % repr(defaults['width']))

optparser.add_option('--ignore-highway', dest='use_highway',
                     action='store_false', help='Ignore differences between highway tags (e.g. collapse primary and secondary) when they share a name.')

if __name__ == '__main__':
    
    options, (input_file, output_file) = optparser.parse_args()
    
    buffer = options.width / 2
    buffer *= (2 * pi * earth_radius) / (2**(options.zoom + 8))
    
    #
    # Input
    #
    
    input = open_file(input_file, 'r')
    
    ways, nodes = parse_street_waynodes(input, options.use_highway)
    multilines = waynode_multilines(ways, nodes)
    
    #
    # Output
    #
    
    kwargs = dict(buffer=buffer, density=buffer/2, min_length=2*buffer, min_area=(buffer**2)/4)
    
    if options.use_highway:
        def key_properties((name, highway)):
            return dict(name=name, highway=highway,
                        zoomlevel=options.zoom, pixelwidth=options.width,
                        shortname=short_street_name(name))
    else:
        def key_properties((name, )):
            return dict(name=name,
                        zoomlevel=options.zoom, pixelwidth=options.width,
                        shortname=short_street_name(name))

    print >> stderr, 'Buffer: %(buffer).1f, density: %(density).1f, minimum length: %(min_length).1f, minimum area: %(min_area).1f.' % kwargs
    print >> stderr, '-' * 20

    geojson = multilines_geojson(multilines, key_properties, **kwargs)
    output = open_file(output_file, 'w')
    dump(geojson, output)

########NEW FILE########
__FILENAME__ = skeletron-pgdump-route-rels
#!/usr/bin/env python
from sys import stdout, stderr
from bz2 import BZ2File
from xml.etree.ElementTree import Element, ElementTree
from itertools import count
from multiprocessing import JoinableQueue, Process

from psycopg2 import connect
from shapely.geometry import LineString

def write_groups(queue):
    '''
    '''
    names = ('routes-%06d.osm.bz2' % id for id in count(1))
    
    while True:
        try:
            group = queue.get(timeout=300)
        except:
            print 'bah'
            break
        
        tree = make_group_tree(group)
        file = BZ2File(names.next(), mode='w')

        tree.write(file)
        file.close()

def get_relations_list(db):
    '''
    '''
    db.execute('''SELECT id, tags
                  FROM planet_osm_rels
                  WHERE 'network' = ANY(tags)
                    AND 'ref' = ANY(tags)
                  ''')
    
    relations = []
    
    for (id, tags) in db.fetchall():
        tags = dict([keyval for keyval in zip(tags[0::2], tags[1::2])])
        
        if 'network' not in tags or 'ref' not in tags:
            continue
        
        network = tags.get('network', '')
        route = tags.get('route', '')
        
        if route == 'route_master' and 'route_master' in tags:
            route = tags.get('route_master', '')

        # Skip bike
        if network in ('lcn', 'rcn', 'ncn', 'icn', 'mtb'):
            continue
        
        # Skip walking
        if network in ('lwn', 'rwn', 'nwn', 'iwn'):
            continue

        # Skip buses, trains
        if route in ('bus', 'bicycle', 'tram', 'train', 'subway', 'light_rail'):
            continue
        
        # if tags.get('network', '') not in ('US:I', ): continue
        
        relations.append((id, tags))
    
    return relations

def get_relation_ways(db, rel_id):
    '''
    '''
    rel_ids = [rel_id]
    rels_seen = set()
    way_ids = set()
    
    while rel_ids:
        rel_id = rel_ids.pop(0)
        
        if rel_id in rels_seen:
            break
        
        rels_seen.add(rel_id)
        
        db.execute('''SELECT members
                      FROM planet_osm_rels
                      WHERE id = %d''' \
                    % rel_id)
        
        try:
            (members, ) = db.fetchone()

        except TypeError:
            # missing relation
            continue
        
        if not members:
            continue
        
        for member in members[0::2]:
            if member.startswith('r'):
                rel_ids.append(int(member[1:]))
            
            elif member.startswith('w'):
                way_ids.add(int(member[1:]))
    
    return way_ids

def get_way_tags(db, way_id):
    '''
    '''
    db.execute('''SELECT tags
                  FROM planet_osm_ways
                  WHERE id = %d''' \
                % way_id)
    
    try:
        (tags, ) = db.fetchone()
        tags = dict([keyval for keyval in zip(tags[0::2], tags[1::2])])

    except TypeError:
        # missing way
        return dict()
    
    return tags

def get_way_linestring(db, way_id):
    '''
    '''
    db.execute('SELECT SRID(way) FROM planet_osm_point LIMIT 1')
    
    (srid, ) = db.fetchone()
    
    if srid not in (4326, 900913):
        raise Exception('Unknown SRID %d' % srid)
    
    db.execute('''SELECT X(location) AS lon, Y(location) AS lat
                  FROM (
                    SELECT
                      CASE
                      WHEN %s = 900913
                      THEN Transform(SetSRID(MakePoint(n.lon * 0.01, n.lat * 0.01), 900913), 4326)
                      WHEN %s = 4326
                      THEN MakePoint(n.lon * 0.0000001, n.lat * 0.0000001)
                      END AS location
                    FROM (
                      SELECT unnest(nodes)::int AS id
                      FROM planet_osm_ways
                      WHERE id = %d
                    ) AS w,
                    planet_osm_nodes AS n
                    WHERE n.id = w.id
                  ) AS points''' \
                % (srid, srid, way_id))
    
    coords = db.fetchall()
    
    if len(coords) < 2:
        return None
    
    return LineString(coords)

def cascaded_union(shapes):
    '''
    '''
    if len(shapes) == 0:
        return None
    
    if len(shapes) == 1:
        return shapes[0]
    
    if len(shapes) == 2:
        if shapes[0] and shapes[1]:
            return shapes[0].union(shapes[1])
        
        if shapes[0] is None:
            return shapes[1]
        
        if shapes[1] is None:
            return shapes[0]
        
        return None
    
    cut = len(shapes) / 2
    
    shapes1 = cascaded_union(shapes[:cut])
    shapes2 = cascaded_union(shapes[cut:])
    
    return cascaded_union([shapes1, shapes2])

def relation_key(tags):
    '''
    '''
    return (tags.get('network', ''), tags.get('ref', ''), tags.get('modifier', ''))

def gen_relation_groups(relations):
    '''
    '''
    relation_keys = [relation_key(tags) for (id, tags) in relations]
    
    group, coords, last_key = [], 0, None
    
    for (key, (id, tags)) in sorted(zip(relation_keys, relations)):

        if coords > 100000 and key != last_key:
            yield group
            group, coords = [], 0
        
        way_ids = get_relation_ways(db, id)
        way_tags = [get_way_tags(db, way_id) for way_id in way_ids]
        way_lines = [get_way_linestring(db, way_id) for way_id in way_ids]
        rel_coords = sum([len(line.coords) for line in way_lines if line])
        #multiline = cascaded_union(way_lines)
        
        print >> stderr, ', '.join(key), '--', rel_coords, 'nodes'
        
        group.append((id, tags, way_tags, way_lines))
        coords += rel_coords
        last_key = key

    yield group

def make_group_tree(group):
    '''
    '''
    ids = (str(-id) for id in count(1))
    osm = Element('osm', dict(version='0.6'))

    for (id, tags, way_tags, way_lines) in group:
    
        rel = Element('relation', dict(id=ids.next(), version='1', timestamp='0000-00-00T00:00:00Z'))
        
        for (k, v) in tags.items():
            rel.append(Element('tag', dict(k=k, v=v)))
        
        for (tags, line) in zip(way_tags, way_lines):
            if not line:
                continue
        
            way = Element('way', dict(id=ids.next(), version='1', timestamp='0000-00-00T00:00:00Z'))
            
            for (k, v) in tags.items():
                way.append(Element('tag', dict(k=k, v=v)))
            
            for coord in line.coords:
                lon, lat = '%.7f' % coord[0], '%.7f' % coord[1]
                node = Element('node', dict(id=ids.next(), lat=lat, lon=lon, version='1', timestamp='0000-00-00T00:00:00Z'))
                nd = Element('nd', dict(ref=node.attrib['id']))

                osm.append(node)
                way.append(nd)
            
            rel.append(Element('member', dict(type='way', ref=way.attrib['id'])))
            
            osm.append(way)
        
        osm.append(rel)
    
    return ElementTree(osm)

if __name__ == '__main__':

    queue = JoinableQueue()
    
    group_writer = Process(target=write_groups, args=(queue, ))
    group_writer.start()
    
    db = connect(host='localhost', user='gis', database='gis', password='gis').cursor()
    
    relations = get_relations_list(db)
    
    for group in gen_relation_groups(relations):
        queue.put(group)

        print >> stderr, '-->', len(group), 'relations'
        print >> stderr, '-' * 80
    
    group_writer.join()

########NEW FILE########
__FILENAME__ = voronoi-look
from math import pi
from time import sleep
from subprocess import Popen, PIPE

from networkx import Graph
from shapely.wkt import loads
from shapely.geometry import Point, LineString
from cairo import Context, ImageSurface, FORMAT_RGB24

# select ST_AsText(ST_Segmentize(ST_Union(ST_Buffer(way, 20, 4)), 20)) from remirrorosm_line where osm_id in (27808429, 27808433, 22942318);
wkt = 'POLYGON((-13610694.9959215 4552437.939579,-13610675.1772861 4552435.25225831,-13610655.3586508 4552432.56493762,-13610635.5400154 4552429.87761693,-13610626.9926793 4552428.71863536,-13610625.8584033 4552428.53148997,-13610606.2269133 4552424.70989326,-13610592.1084033 4552421.96148997,-13610590.2349216 4552421.50201298,-13610571.0629086 4552415.80693456,-13610551.8908956 4552410.11185613,-13610532.7188826 4552404.41677771,-13610513.5468697 4552398.72169929,-13610494.3748567 4552393.02662086,-13610475.2028437 4552387.33154244,-13610456.0308307 4552381.63646402,-13610451.6875002 4552380.34627046,-13610441.4120953 4552378.64053685,-13610430.0615582 4552377.95345833,-13610420.2417295 4552374.67464117,-13610413.376917 4552366.92518788,-13610411.4825354 4552357.64382477,-13610405.9655652 4552356.58193289,-13610398.1397912 4552349.80425356,-13610394.7513117 4552340.02172404,-13610396.7080671 4552329.85556522,-13610403.4857464 4552322.02979115,-13610413.268276 4552318.64131167,-13610423.718276 4552317.89131167,-13610427.105426 4552317.93582182,-13610436.775426 4552318.88582182,-13610439.7960081 4552319.41890443,-13610459.1671037 4552324.39491254,-13610473.2360081 4552328.00890443,-13610474.0340953 4552328.23163654,-13610493.1824588 4552334.00573185,-13610512.3308222 4552339.77982716,-13610531.4791857 4552345.55392247,-13610534.1152806 4552346.34882401,-13610553.3280304 4552351.90492409,-13610572.5407801 4552357.46102418,-13610587.4661001 4552361.77725028,-13610589.0433615 4552362.30537655,-13610602.2021246 4552367.32909108,-13610612.0242197 4552370.93361464,-13610631.2349911 4552376.49655111,-13610637.6329365 4552378.3492286,-13610637.9662497 4552378.44889749,-13610657.0773522 4552384.3451472,-13610676.1884547 4552390.24139692,-13610695.2995573 4552396.13764663,-13610705.4162497 4552399.25889749,-13610705.5940903 4552399.37065701,-13610705.8037811 4552399.38279127,-13610724.7909898 4552405.66657233,-13610733.7537811 4552408.63279127,-13610736.292745 4552409.671207,-13610754.241538 4552418.49395204,-13610772.190331 4552427.31669708,-13610790.139124 4552436.13944211,-13610808.087917 4552444.96218715,-13610826.03671 4552453.78493219,-13610842.812745 4552462.031207,-13610843.0857015 4552462.16797557,-13610860.8977259 4552471.26367707,-13610878.7097504 4552480.35937856,-13610896.5217748 4552489.45508006,-13610914.3337992 4552498.55078155,-13610932.1458237 4552507.64648305,-13610949.9578481 4552516.74218454,-13610967.7698725 4552525.83788604,-13610975.6599536 4552529.86695206,-13610993.0236957 4552538.01869887,-13611012.6842843 4552541.68765773,-13611032.3448728 4552545.35661659,-13611052.0054613 4552549.02557545,-13611071.6660498 4552552.69453431,-13611091.3266383 4552556.36349317,-13611110.9872269 4552560.03245204,-13611130.6478154 4552563.7014109,-13611150.3084039 4552567.37036976,-13611169.9689924 4552571.03932862,-13611173.3989589 4552571.67941148,-13611173.6954182 4552571.73705485,-13611193.2983633 4552575.70247304,-13611212.9013085 4552579.66789123,-13611232.5042536 4552583.63330942,-13611252.1071988 4552587.59872761,-13611271.7101439 4552591.56414581,-13611291.3130891 4552595.529564,-13611310.9160342 4552599.49498219,-13611330.5189794 4552603.46040038,-13611350.1219245 4552607.42581857,-13611363.4754182 4552610.12705485,-13611367.5306699 4552611.40873218,-13611383.2006699 4552618.26873218,-13611383.748143 4552618.51828381,-13611399.9060625 4552626.17905955,-13611404.5411741 4552627.22558359,-13611412.2295174 4552623.93943686,-13611422.4779039 4552622.47306381,-13611432.0864536 4552626.32734078,-13611438.4805631 4552634.46951737,-13611439.9469362 4552644.71790393,-13611436.0926592 4552654.32645356,-13611427.9504826 4552660.72056314,-13611414.3104826 4552666.55056314,-13611402.0452393 4552667.66892317,-13611388.9352393 4552664.70892317,-13611384.771857 4552663.27171619,-13611366.8837165 4552654.79060992,-13611353.4484308 4552648.90892135,-13611333.8454857 4552644.94350316,-13611314.2425405 4552640.97808497,-13611294.6395954 4552637.01266678,-13611275.0366502 4552633.04724859,-13611255.4337051 4552629.0818304,-13611235.8307599 4552625.1164122,-13611216.2278148 4552621.15099401,-13611196.6248696 4552617.18557582,-13611177.0219245 4552613.22015763,-13611165.9125938 4552610.97288603,-13611146.2520053 4552607.30392717,-13611126.5914168 4552603.63496831,-13611106.9308283 4552599.96600945,-13611087.2702397 4552596.29705059,-13611067.6096512 4552592.62809173,-13611047.9490627 4552588.95913287,-13611028.2884742 4552585.290174,-13611008.6278857 4552581.62121514,-13610988.9672971 4552577.95225628,-13610983.1710411 4552576.87058852,-13610978.340645 4552575.31416981,-13610960.2364752 4552566.81481482,-13610958.360645 4552565.93416981,-13610957.7642985 4552565.64202443,-13610939.9522741 4552556.54632294,-13610922.1402496 4552547.45062144,-13610904.3282252 4552538.35491994,-13610886.5162008 4552529.25921845,-13610868.7041763 4552520.16351696,-13610850.8921519 4552511.06781546,-13610833.0801275 4552501.97211397,-13610825.0302547 4552497.86145042,-13610807.0814618 4552489.03870538,-13610789.1326688 4552480.21596035,-13610771.1838758 4552471.39321531,-13610753.2350828 4552462.57047027,-13610735.2862898 4552453.74772524,-13610719.8810468 4552446.17526448,-13610700.8938381 4552439.89148342,-13610694.9959215 4552437.939579))'

# select ST_AsText(ST_Segmentize(ST_Union(ST_Buffer(way, 10, 3)), 5)) from remirrorosm_line where osm_id in (22942317, 22942316);
wkt = 'POLYGON((-13610265.0824382 4552448.50997286,-13610263.3110593 4552451.25361468,-13610258.8620834 4552453.53541511,-13610258.7051405 4552453.61590831,-13610253.7113141 4552453.36751749,-13610253.535151 4552453.35875521,-13610249.3345659 4552450.64672925,-13610249.1863853 4552450.55105934,-13610246.9045849 4552446.10208341,-13610246.8240917 4552445.94514053,-13610247.0724825 4552440.95131414,-13610247.0812448 4552440.77515102,-13610248.6136693 4552436.01577342,-13610250.1460938 4552431.25639581,-13610251.6785183 4552426.49701821,-13610253.2109427 4552421.7376406,-13610254.7433672 4552416.978263,-13610256.2757917 4552412.21888539,-13610257.8082162 4552407.45950779,-13610259.3406407 4552402.70013018,-13610260.8730652 4552397.94075258,-13610261.1967278 4552396.9355268,-13610262.5275078 4552392.11587694,-13610263.8582877 4552387.29622709,-13610265.1890677 4552382.47657724,-13610266.4007003 4552378.08844008,-13610266.4173412 4552378.02889051,-13610267.7778959 4552373.21756109,-13610269.1384506 4552368.40623167,-13610270.4990054 4552363.59490225,-13610271.8595601 4552358.78357283,-13610273.2201149 4552353.97224341,-13610274.5806696 4552349.16091399,-13610275.9412244 4552344.34958457,-13610277.3017791 4552339.53825515,-13610278.6623338 4552334.72692573,-13610279.1738364 4552332.91809926,-13610280.3442039 4552328.05700473,-13610281.5145713 4552323.1959102,-13610282.6849388 4552318.33481567,-13610283.2041525 4552316.1782734,-13610283.9823919 4552311.23921039,-13610284.7606314 4552306.30014739,-13610285.5388708 4552301.36108439,-13610285.5924503 4552301.02104457,-13610285.7999127 4552296.02535048,-13610286.0073751 4552291.0296564,-13610286.2148375 4552286.03396232,-13610286.2933058 4552284.14444567,-13610285.8921183 4552279.1605668,-13610285.4909309 4552274.17668792,-13610285.0897434 4552269.19280905,-13610284.8957189 4552266.78247762,-13610283.9583587 4552261.87112792,-13610283.0209985 4552256.95977823,-13610282.0836383 4552252.04842853,-13610281.4516401 4552248.73703972,-13610280.2831386 4552243.87549633,-13610279.1146371 4552239.01395293,-13610277.9461355 4552234.15240954,-13610276.777634 4552229.29086614,-13610275.8369132 4552225.37700306,-13610275.780024 4552225.12616149,-13610274.7369433 4552220.2361735,-13610273.6938625 4552215.34618551,-13610272.6507818 4552210.45619751,-13610271.607701 4552205.56620952,-13610270.5646203 4552200.67622153,-13610269.5215395 4552195.78623354,-13610268.4784588 4552190.89624554,-13610267.4353781 4552186.00625755,-13610266.3922973 4552181.11626956,-13610265.3492166 4552176.22628157,-13610264.3061358 4552171.33629358,-13610263.2630551 4552166.44630558,-13610262.7596781 4552164.0864621,-13610261.3009174 4552159.30399231,-13610259.8421567 4552154.52152252,-13610258.383396 4552149.73905274,-13610256.9246354 4552144.95658295,-13610255.4658747 4552140.17411317,-13610255.4150604 4552140.00752138,-13610255.384457 4552139.11457027,-13610255.0517026 4552138.28537024,-13610255.2971803 4552136.56799271,-13610255.2377587 4552134.83417785,-13610255.6577309 4552134.04555781,-13610255.7841571 4552133.16107228,-13610256.8554358 4552131.79651856,-13610257.6708826 4552130.26528004,-13610258.4288992 4552129.79230118,-13610258.9806303 4552129.08952732,-13610260.5906617 4552128.44342849,-13610262.0624786 4552127.52506043,-13610262.9554297 4552127.49445705,-13610263.7846298 4552127.16170256,-13610265.5020073 4552127.40718027,-13610267.2358222 4552127.34775866,-13610268.0244422 4552127.7677309,-13610268.9089277 4552127.89415708,-13610270.2734814 4552128.96543578,-13610271.80472 4552129.78088258,-13610272.2776988 4552130.53889924,-13610272.9804727 4552131.09063029,-13610275.9801575 4552135.09086663,-13610278.9798424 4552139.09110296,-13610281.9795272 4552143.0913393,-13610284.9792121 4552147.09157564,-13610287.978897 4552151.09181198,-13610288.2104727 4552151.40063029,-13610288.7104838 4552152.13295383,-13610291.3440069 4552156.38319572,-13610293.97753 4552160.63343761,-13610296.4804838 4552164.67295383,-13610296.8544499 4552165.3308636,-13610299.1590181 4552169.76808857,-13610301.4635863 4552174.20531354,-13610303.7681545 4552178.64253851,-13610306.0727227 4552183.07976348,-13610308.3772909 4552187.51698845,-13610310.6818591 4552191.95421341,-13610312.9864273 4552196.39143838,-13610315.2909955 4552200.82866335,-13610317.5955637 4552205.26588832,-13610319.9001319 4552209.70311329,-13610320.9844499 4552211.7908636,-13610321.1167911 4552212.05515094,-13610323.2892157 4552216.55854651,-13610325.4616402 4552221.06194208,-13610327.5567911 4552225.40515094,-13610328.1140391 4552226.82952825,-13610329.574275 4552231.61154782,-13610331.0345109 4552236.39356739,-13610332.4440391 4552241.00952824,-13610332.6472805 4552241.78518494,-13610333.719688 4552246.66882518,-13610334.7920956 4552251.55246543,-13610335.3372805 4552254.03518494,-13610335.5571499 4552255.67320958,-13610335.8105451 4552260.66678454,-13610336.0639403 4552265.66035949,-13610336.3071499 4552270.45320958,-13610336.2816482 4552271.83496585,-13610335.8441653 4552276.81578994,-13610335.4066823 4552281.79661404,-13610334.9691994 4552286.77743814,-13610334.9316482 4552287.20496585,-13610334.8101327 4552288.11095177,-13610333.9196568 4552293.0310181,-13610333.0291809 4552297.95108443,-13610332.4301327 4552301.26095177,-13610332.1995327 4552302.24710706,-13610330.8159792 4552307.05187341,-13610329.4324256 4552311.85663975,-13610328.1595327 4552316.27710706,-13610327.9950989 4552316.79482968,-13610326.3526841 4552321.51737915,-13610324.7102693 4552326.23992862,-13610323.0678544 4552330.96247809,-13610321.4254396 4552335.68502756,-13610319.7830247 4552340.40757703,-13610318.1406099 4552345.1301265,-13610316.4981951 4552349.85267597,-13610314.8557802 4552354.57522543,-13610313.2133654 4552359.2977749,-13610311.5709505 4552364.02032437,-13610309.9285357 4552368.74287384,-13610308.2861209 4552373.46542331,-13610307.7971518 4552374.87138996,-13610306.4510612 4552379.68678612,-13610305.1049707 4552384.50218228,-13610304.0007923 4552388.45218114,-13610303.9420838 4552388.65399572,-13610302.495086 4552393.44003763,-13610301.0480881 4552398.22607955,-13610299.6010902 4552403.01212146,-13610298.1540924 4552407.79816337,-13610296.7070945 4552412.58420529,-13610295.2600967 4552417.3702472,-13610293.8130988 4552422.15628911,-13610292.3661009 4552426.94233103,-13610290.9191031 4552431.72837294,-13610289.4721052 4552436.51441485,-13610288.0251074 4552441.30045677,-13610286.5781095 4552446.08649868,-13610285.6088636 4552449.29234416,-13610284.283965 4552454.11361409,-13610282.9590664 4552458.93488402,-13610281.6341678 4552463.75615395,-13610280.3092693 4552468.57742388,-13610279.0593973 4552473.12567391,-13610277.8691087 4552477.98192894,-13610276.67882 4552482.83818397,-13610275.4885313 4552487.69443899,-13610274.2982427 4552492.55069402,-13610273.107954 4552497.40694905,-13610271.9176653 4552502.26320408,-13610271.3325101 4552504.65057732,-13610268.9258882 4552509.0332901,-13610268.8409918 4552509.18789547,-13610264.5654397 4552511.78012514,-13610264.4146146 4552511.87156911,-13610259.4157631 4552511.97872983,-13610259.2394227 4552511.98251006,-13610254.8567099 4552509.57588821,-13610254.7021045 4552509.49099178,-13610252.1098749 4552505.21543973,-13610252.0184309 4552505.06461459,-13610251.9112702 4552500.06576306,-13610251.9074899 4552499.88942268,-13610253.0977786 4552495.03316765,-13610254.2880673 4552490.17691262,-13610255.4783559 4552485.32065759,-13610256.6686446 4552480.46440256,-13610257.8589333 4552475.60814753,-13610259.0492219 4552470.75189251,-13610259.6674899 4552468.22942268,-13610259.7374601 4552467.96020283,-13610261.0623587 4552463.1389329,-13610262.3872573 4552458.31766297,-13610263.7121559 4552453.49639304,-13610265.0370545 4552448.67512311,-13610265.0824382 4552448.50997286),(-13610289.8571841 4552195.25037617,-13610290.9002648 4552200.14036417,-13610291.9433456 4552205.03035216,-13610292.9864263 4552209.92034015,-13610294.029507 4552214.81032814,-13610295.0725878 4552219.70031613,-13610295.3131445 4552220.82805192,-13610296.481646 4552225.68959531,-13610297.6501476 4552230.55113871,-13610298.8186491 4552235.4126821,-13610299.9871506 4552240.2742255,-13610300.9530868 4552244.29299694,-13610301.0526994 4552244.75527959,-13610301.9900596 4552249.66662929,-13610302.9274198 4552254.57797899,-13610303.86478 4552259.48932869,-13610304.6426994 4552263.56527959,-13610304.7877578 4552264.63762512,-13610305.1889452 4552269.62150399,-13610305.5901326 4552274.60538287,-13610305.9913201 4552279.58926174,-13610306.2777578 4552283.14762512,-13610306.3013882 4552284.36492476,-13610306.0939258 4552289.36061884,-13610305.8864634 4552294.35631292,-13610305.679001 4552299.352007,-13610305.5513882 4552302.42492476,-13610305.438126 4552303.56647891,-13610304.6598866 4552308.50554192,-13610303.8816471 4552313.44460492,-13610303.1034076 4552318.38366792,-13610302.898126 4552319.68647891,-13610302.7421891 4552320.4707349,-13610301.5718216 4552325.33182943,-13610300.4014542 4552330.19292396,-13610299.2310867 4552335.05401849,-13610298.5721891 4552337.7907349,-13610298.4726588 4552338.17110949,-13610297.1121041 4552342.98243891,-13610295.7515494 4552347.79376833,-13610294.4999474 4552352.21980797,-13610296.1423623 4552347.4972585,-13610297.7847771 4552342.77470904,-13610299.4271919 4552338.05215957,-13610301.0696068 4552333.3296101,-13610302.7120216 4552328.60706063,-13610304.3544365 4552323.88451116,-13610305.9968513 4552319.16196169,-13610307.6392661 4552314.43941222,-13610309.0156508 4552310.48179777,-13610310.3992043 4552305.67703142,-13610311.7827579 4552300.87226508,-13610312.8401668 4552297.20012453,-13610313.7306427 4552292.2800582,-13610314.6211186 4552287.35999187,-13610315.0483839 4552284.99926137,-13610315.4858668 4552280.01843727,-13610315.9233497 4552275.03761318,-13610316.2977472 4552270.77502909,-13610316.044352 4552265.78145413,-13610315.7909568 4552260.78787917,-13610315.6248728 4552257.51491846,-13610314.5524653 4552252.63127821,-13610313.4800578 4552247.74763796,-13610313.1987788 4552246.46672087,-13610311.7385429 4552241.6847013,-13610310.2783071 4552236.90268173,-13610309.2099602 4552233.40403079,-13610307.0375357 4552228.90063522,-13610304.8651111 4552224.39723965,-13610303.1674263 4552220.87797072,-13610300.8628581 4552216.44074575,-13610298.55829 4552212.00352078,-13610296.2537218 4552207.56629581,-13610293.9491536 4552203.12907084,-13610291.6445854 4552198.69184587,-13610289.8571841 4552195.25037617))'

# select ST_AsText(ST_Segmentize(ST_Union(ST_Buffer(way, 15, 3)), 5)) from remirrorosm_line where osm_id in (27808433, 22942315, 20161650, 22942318, 22942317, 22942316, 6385475, 22942319);
wkt = 'POLYGON((-13610242.3145726 4552439.38938136,-13610242.3218672 4552439.24272654,-13610243.8542917 4552434.48334893,-13610245.3867162 4552429.72397133,-13610246.9191406 4552424.96459372,-13610248.4515651 4552420.20521612,-13610249.9839896 4552415.44583851,-13610251.5164141 4552410.6864609,-13610253.0488386 4552405.9270833,-13610254.5812631 4552401.16770569,-13610256.1136876 4552396.40832809,-13610256.4050917 4552395.50329018,-13610257.7358717 4552390.68364032,-13610259.0666516 4552385.86399047,-13610260.3974316 4552381.04434062,-13610261.5810504 4552376.75766012,-13610261.6060117 4552376.66833577,-13610262.9665665 4552371.85700635,-13610264.3271212 4552367.04567693,-13610265.687676 4552362.23434751,-13610267.0482307 4552357.42301809,-13610268.4087855 4552352.61168867,-13610269.7693402 4552347.80035925,-13610271.1298949 4552342.98902982,-13610272.4904497 4552338.1777004,-13610273.8510044 4552333.36637098,-13610274.3357546 4552331.65214893,-13610275.5061221 4552326.7910544,-13610276.6764895 4552321.92995987,-13610277.846857 4552317.06886534,-13610278.2962287 4552315.20241009,-13610279.0744682 4552310.26334709,-13610279.8527076 4552305.32428409,-13610280.6086755 4552300.52656685,-13610280.8161379 4552295.53087277,-13610281.0236002 4552290.53517869,-13610281.2310626 4552285.5394846,-13610281.2849586 4552284.24166849,-13610280.8837712 4552279.25778962,-13610280.4825838 4552274.27391074,-13610280.0813963 4552269.29003187,-13610279.9335784 4552267.45371646,-13610278.9962182 4552262.54236677,-13610278.058858 4552257.63101707,-13610277.1214978 4552252.71966737,-13610276.5624602 4552249.79055955,-13610275.3939587 4552244.92901615,-13610274.2254571 4552240.06747276,-13610273.0569556 4552235.20592937,-13610271.8884541 4552230.34438597,-13610270.9753698 4552226.54550458,-13610270.890036 4552226.16924223,-13610269.8469553 4552221.27925424,-13610268.8038745 4552216.38926625,-13610267.7607938 4552211.49927826,-13610266.717713 4552206.60929027,-13610265.6746323 4552201.71930227,-13610264.6315516 4552196.82931428,-13610263.5884708 4552191.93932629,-13610262.5453901 4552187.0493383,-13610261.5023093 4552182.15935031,-13610260.4592286 4552177.26936231,-13610259.4161478 4552172.37937432,-13610258.3730671 4552167.48938633,-13610257.9145172 4552165.33969315,-13610256.4557565 4552160.55722336,-13610254.9969958 4552155.77475358,-13610253.5382351 4552150.99228379,-13610252.0794744 4552146.20981401,-13610250.6325906 4552141.46628207,-13610250.5866856 4552140.12685541,-13610250.0875538 4552138.88305536,-13610250.4557704 4552136.30698906,-13610250.366638 4552133.70626677,-13610250.9965964 4552132.52333672,-13610251.1862356 4552131.19660841,-13610252.7931537 4552129.14977784,-13610254.0163239 4552126.85292005,-13610255.1533489 4552126.14345176,-13610255.9809454 4552125.08929098,-13610258.3959926 4552124.12014274,-13610260.6037179 4552122.74259064,-13610261.9431446 4552122.69668557,-13610263.1869446 4552122.19755385,-13610265.7630109 4552122.56577041,-13610268.3637332 4552122.47663798,-13610269.5466633 4552123.10659635,-13610270.8733916 4552123.29623563,-13610272.9202222 4552124.90315368,-13610275.2170799 4552126.12632388,-13610275.9265482 4552127.26334885,-13610276.980709 4552128.09094543,-13610279.9803939 4552132.09118177,-13610282.9800787 4552136.09141811,-13610285.9797636 4552140.09165445,-13610288.9794484 4552144.09189078,-13610291.9791333 4552148.09212712,-13610292.210709 4552148.40094543,-13610292.9607257 4552149.49943074,-13610295.5942488 4552153.74967263,-13610298.2277719 4552157.99991453,-13610300.7307257 4552162.03943074,-13610301.2916749 4552163.02629541,-13610303.5962431 4552167.46352037,-13610305.9008113 4552171.90074534,-13610308.2053795 4552176.33797031,-13610310.5099477 4552180.77519528,-13610312.8145159 4552185.21242025,-13610315.1190841 4552189.64964522,-13610317.4236523 4552194.08687018,-13610319.7282205 4552198.52409515,-13610322.0327887 4552202.96132012,-13610324.3373569 4552207.39854509,-13610325.4216749 4552209.48629541,-13610325.6201867 4552209.88272641,-13610327.7926112 4552214.38612198,-13610329.9650358 4552218.88951755,-13610332.0601867 4552223.23272641,-13610332.1476539 4552223.45630049,-13610332.1884762 4552223.50564516,-13610334.2699278 4552228.05180389,-13610336.3513794 4552232.59796262,-13610338.432831 4552237.14412135,-13610340.5142826 4552241.69028008,-13610342.5957342 4552246.23643881,-13610344.6771859 4552250.78259754,-13610346.7586375 4552255.32875626,-13610347.987423 4552258.0125823,-13610350.5378974 4552262.313173,-13610353.0883718 4552266.61376371,-13610354.2049928 4552268.4966016,-13610357.3410778 4552272.39082433,-13610360.4771628 4552276.28504706,-13610362.1777291 4552278.39671936,-13610365.8875782 4552281.74888578,-13610369.5974273 4552285.10105221,-13610373.1172401 4552288.2815046,-13610377.2327898 4552291.12091486,-13610381.3483395 4552293.96032512,-13610385.4638892 4552296.79973538,-13610389.5794389 4552299.63914564,-13610393.6949886 4552302.47855591,-13610397.8105383 4552305.31796617,-13610401.926088 4552308.15737643,-13610403.7596983 4552309.42242534,-13610408.2067145 4552311.70804264,-13610412.6537308 4552313.99365993,-13610413.0779098 4552314.21167373,-13610417.7005244 4552316.11730602,-13610422.3231389 4552318.02293832,-13610423.3909309 4552318.46312619,-13610428.0706429 4552320.22389199,-13610432.7503548 4552321.98465779,-13610437.4300667 4552323.7454236,-13610439.3404252 4552324.46420586,-13610444.1831991 4552325.70820788,-13610449.025973 4552326.95220991,-13610453.8687469 4552328.19621194,-13610458.7115208 4552329.44021396,-13610463.5542947 4552330.68421599,-13610468.3970686 4552331.92821801,-13610471.9920061 4552332.85167833,-13610472.5905715 4552333.0187274,-13610477.3776623 4552334.46225123,-13610482.1647532 4552335.90577506,-13610486.9518441 4552337.34929889,-13610491.7389349 4552338.79282271,-13610496.5260258 4552340.23634654,-13610501.3131167 4552341.67987037,-13610506.1002075 4552343.1233942,-13610510.8872984 4552344.56691803,-13610515.6743893 4552346.01044185,-13610520.4614801 4552347.45396568,-13610525.248571 4552348.89748951,-13610530.0356619 4552350.34101334,-13610532.6989605 4552351.144118,-13610537.5021479 4552352.53314302,-13610542.3053353 4552353.92216804,-13610547.1085227 4552355.31119306,-13610551.9117102 4552356.70021808,-13610556.7148976 4552358.0892431,-13610561.518085 4552359.47826813,-13610566.3212725 4552360.86729315,-13610571.1244599 4552362.25631817,-13610575.9276473 4552363.64534319,-13610580.7308348 4552365.03436821,-13610585.5340222 4552366.42339323,-13610586.0770751 4552366.58043771,-13610587.2600211 4552366.97653241,-13610591.931177 4552368.75987279,-13610596.6023329 4552370.54321317,-13610600.4490934 4552372.0118183,-13610605.1429978 4552373.73439262,-13610609.8369021 4552375.45696694,-13610610.4656648 4552375.68771098,-13610615.2683576 4552377.0784451,-13610620.0710505 4552378.46917922,-13610624.8737433 4552379.85991333,-13610629.6764362 4552381.25064745,-13610634.479129 4552382.64138157,-13610636.2422024 4552383.15192145,-13610636.4921873 4552383.22667311,-13610641.2699629 4552384.70073554,-13610646.0477385 4552386.17479797,-13610650.8255142 4552387.6488604,-13610655.6032898 4552389.12292283,-13610660.3810654 4552390.59698526,-13610665.1588411 4552392.07104769,-13610669.9366167 4552393.54511012,-13610674.7143923 4552395.01917254,-13610679.4921679 4552396.49323497,-13610684.2699436 4552397.9672974,-13610689.0477192 4552399.44135983,-13610693.8254948 4552400.91542226,-13610698.6032705 4552402.38948469,-13610703.3810461 4552403.86354712,-13610703.9421873 4552404.03667311,-13610706.2180835 4552405.46690387,-13610708.6974542 4552406.50516399,-13610709.456004 4552407.50169506,-13610710.51639 4552408.16806844,-13610711.7722585 4552410.5446327,-13610713.4003265 4552412.68347773,-13610713.5589843 4552413.92577383,-13610714.1441188 4552415.03306309,-13610714.0434508 4552417.71916238,-13610714.3839765 4552420.38549052,-13610713.9002302 4552421.54067941,-13610713.8533269 4552422.79218729,-13610712.4230961 4552425.06808348,-13610711.384836 4552427.54745425,-13610710.3883049 4552428.306004,-13610709.7219316 4552429.36638997,-13610707.3453673 4552430.62225851,-13610705.2065223 4552432.25032653,-13610703.9642262 4552432.40898434,-13610702.8569369 4552432.99411885,-13610700.1708376 4552432.89345077,-13610697.5045095 4552433.23397652,-13610692.5498506 4552432.56214635,-13610687.5951918 4552431.89031618,-13610682.640533 4552431.218486,-13610677.6858741 4552430.54665583,-13610672.7312153 4552429.87482566,-13610667.7765564 4552429.20299549,-13610662.8218976 4552428.53116532,-13610657.8672388 4552427.85933514,-13610652.9125799 4552427.18750497,-13610647.9579211 4552426.5156748,-13610643.0032622 4552425.84384463,-13610638.0486034 4552425.17201446,-13610633.0939446 4552424.50018428,-13610628.1392857 4552423.82835411,-13610627.6645095 4552423.76397652,-13610626.8138025 4552423.62361748,-13610621.90593 4552422.6682183,-13610616.9980575 4552421.71281912,-13610612.090185 4552420.75741994,-13610607.1823125 4552419.80202076,-13610602.27444 4552418.84662159,-13610597.3665675 4552417.89122241,-13610593.0638025 4552417.05361748,-13610591.6586912 4552416.70900974,-13610586.8656879 4552415.28524013,-13610582.0726847 4552413.86147053,-13610577.2796814 4552412.43770092,-13610572.4866782 4552411.01393131,-13610567.693675 4552409.59016171,-13610562.9006717 4552408.1663921,-13610558.1076685 4552406.74262249,-13610553.3146652 4552405.31885289,-13610548.521662 4552403.89508328,-13610543.7286587 4552402.47131368,-13610538.9356555 4552401.04754407,-13610534.1426522 4552399.62377446,-13610529.349649 4552398.20000486,-13610524.5566457 4552396.77623525,-13610519.7636425 4552395.35246565,-13610514.9706392 4552393.92869604,-13610510.177636 4552392.50492643,-13610505.3846328 4552391.08115683,-13610500.5916295 4552389.65738722,-13610495.7986263 4552388.23361762,-13610491.005623 4552386.80984801,-13610486.2126198 4552385.3860784,-13610481.4196165 4552383.9623088,-13610476.6266133 4552382.53853919,-13610471.83361 4552381.11476959,-13610467.0406068 4552379.69099998,-13610462.2476035 4552378.26723037,-13610457.4546003 4552376.84346077,-13610452.8131252 4552375.46470285,-13610447.8806246 4552374.64589988,-13610442.9481241 4552373.82709692,-13610441.9740715 4552373.66540264,-13610436.9832069 4552373.36329219,-13610431.9923423 4552373.06118174,-13610431.8852033 4552373.05469633,-13610426.9355912 4552373.76275017,-13610421.9859791 4552374.47080402,-13610417.0363671 4552375.17885787,-13610412.1119607 4552375.88330597,-13610407.2458885 4552377.03280221,-13610402.3798164 4552378.18229845,-13610397.5137442 4552379.33179469,-13610392.647672 4552380.48129094,-13610388.5251096 4552381.45515032,-13610383.8579601 4552383.24894959,-13610379.1908106 4552385.04274886,-13610374.5236612 4552386.83654813,-13610369.8565117 4552388.6303474,-13610365.1893622 4552390.42414667,-13610364.8447282 4552390.5566053,-13610360.4984861 4552393.02848295,-13610356.1522439 4552395.5003606,-13610351.8060018 4552397.97223826,-13610347.4597596 4552400.44411591,-13610344.211609 4552402.291466,-13610340.402309 4552405.53017463,-13610336.5930091 4552408.76888327,-13610332.7837091 4552412.00759191,-13610328.9744091 4552415.24630054,-13610327.568395 4552416.44170917,-13610324.5439746 4552420.4232769,-13610321.5195543 4552424.40484462,-13610318.4951339 4552428.38641235,-13610315.4707136 4552432.36798008,-13610314.4698927 4552433.68553372,-13610311.9439967 4552438.00060607,-13610309.4181007 4552442.31567841,-13610306.8922047 4552446.63075076,-13610304.3663087 4552450.94582311,-13610303.0812373 4552453.14115342,-13610300.7350964 4552457.55653821,-13610298.3889555 4552461.971923,-13610296.0428146 4552466.3873078,-13610293.6966737 4552470.80269259,-13610291.3505328 4552475.21807738,-13610290.8251525 4552476.20683134,-13610288.6551671 4552480.71140274,-13610286.4851818 4552485.21597414,-13610284.3151964 4552489.72054554,-13610282.145211 4552494.22511694,-13610279.9752257 4552498.72968834,-13610277.8052403 4552503.23425973,-13610275.8195163 4552507.35633155,-13610274.6358327 4552512.21420075,-13610273.4521491 4552517.07206995,-13610273.2136076 4552518.05105075,-13610273.1188911 4552518.41940214,-13610271.8124237 4552523.24569917,-13610270.5059563 4552528.0719962,-13610270.2088911 4552529.16940214,-13610270.1892494 4552529.24125383,-13610268.8588314 4552534.06100362,-13610267.5284135 4552538.88075342,-13610266.1979956 4552543.70050322,-13610264.8675776 4552548.52025301,-13610263.5371597 4552553.34000281,-13610262.2067417 4552558.15975261,-13610260.8763238 4552562.9795024,-13610259.5459059 4552567.7992522,-13610258.2154879 4552572.619002,-13610256.88507 4552577.43875179,-13610255.8492494 4552581.19125383,-13610253.3167213 4552585.50243713,-13610251.9164504 4552587.8861519,-13610247.5676251 4552590.35348212,-13610245.1630975 4552591.7177042,-13610240.1632392 4552591.68006219,-13610237.3987462 4552591.65924939,-13610233.0875629 4552589.1267213,-13610230.7038481 4552587.72645038,-13610228.2365179 4552583.37762506,-13610226.8722958 4552580.97309749,-13610226.9053605 4552576.58122847,-13610221.9054939 4552576.5447039,-13610219.9119778 4552576.53014105,-13610215.6002286 4552573.99857655,-13610213.216201 4552572.59883842,-13610210.7478989 4552568.25056465,-13610209.3831394 4552565.84634203,-13610209.419664 4552560.84647543,-13610209.4398589 4552558.08197784,-13610210.7691997 4552553.26193083,-13610212.0985404 4552548.44188381,-13610213.4278811 4552543.62183679,-13610214.7572218 4552538.80178977,-13610216.0865625 4552533.98174275,-13610217.4159033 4552529.16169574,-13610218.745244 4552524.34164872,-13610220.0745847 4552519.5216017,-13610220.6398589 4552517.47197784,-13610220.645939 4552517.44999735,-13610221.9826066 4552512.63197703,-13610223.3192741 4552507.8139567,-13610223.7549809 4552506.24345107,-13610225.0893452 4552501.42479235,-13610226.4237095 4552496.60613362,-13610227.7580738 4552491.7874749,-13610229.0924381 4552486.96881618,-13610230.4268024 4552482.15015746,-13610231.7611667 4552477.33149873,-13610233.095531 4552472.51284001,-13610234.4298953 4552467.69418129,-13610235.7642597 4552462.87552257,-13610237.098624 4552458.05686384,-13610238.4329883 4552453.23820512,-13610239.7673526 4552448.4195464,-13610241.1017169 4552443.60088768,-13610242.1440238 4552439.83690707,-13610242.3145726 4552439.38938136),(-13610333.8162296 4552314.70209972,-13610332.964299 4552317.66066059,-13610332.7176484 4552318.43724452,-13610331.0752336 4552323.15979399,-13610329.4328187 4552327.88234346,-13610327.7904039 4552332.60489293,-13610326.147989 4552337.3274424,-13610324.5055742 4552342.04999187,-13610322.8631594 4552346.77254134,-13610321.2207445 4552351.49509081,-13610320.1075828 4552354.69584211,-13610324.7579749 4552352.8590369,-13610329.408367 4552351.0222317,-13610332.8095844 4552349.67882372,-13610333.1520366 4552349.54837531,-13610337.8459115 4552347.82572083,-13610342.5397864 4552346.10306635,-13610347.2336613 4552344.38041188,-13610351.9275362 4552342.6577574,-13610356.6214111 4552340.93510292,-13610361.315286 4552339.21244844,-13610364.785197 4552337.93898931,-13610360.6665711 4552335.10404294,-13610356.5479453 4552332.26909657,-13610352.4293194 4552329.4341502,-13610348.3106935 4552326.59920383,-13610345.0951609 4552324.38587762,-13610343.7556614 4552323.34764098,-13610339.9831144 4552320.06619478,-13610336.2105674 4552316.78474858,-13610333.8162296 4552314.70209972))'

# select ST_AsText(ST_Segmentize(ST_Union(ST_Buffer(way, 10, 3)), 5)) from remirrorosm_line where osm_id in (27808433, 22942315, 20161650, 22942318, 22942317, 22942316, 6385475, 22942319);
wkt = 'POLYGON((-13610247.0763818 4552440.87292091,-13610247.0812448 4552440.77515102,-13610248.6136693 4552436.01577342,-13610250.1460938 4552431.25639581,-13610251.6785183 4552426.49701821,-13610253.2109427 4552421.7376406,-13610254.7433672 4552416.978263,-13610256.2757917 4552412.21888539,-13610257.8082162 4552407.45950779,-13610259.3406407 4552402.70013018,-13610260.8730652 4552397.94075258,-13610261.1967278 4552396.9355268,-13610262.5275078 4552392.11587694,-13610263.8582877 4552387.29622709,-13610265.1890677 4552382.47657724,-13610266.4007003 4552378.08844008,-13610266.4173412 4552378.02889051,-13610267.7778959 4552373.21756109,-13610269.1384506 4552368.40623167,-13610270.4990054 4552363.59490225,-13610271.8595601 4552358.78357283,-13610273.2201149 4552353.97224341,-13610274.5806696 4552349.16091399,-13610275.9412244 4552344.34958457,-13610277.3017791 4552339.53825515,-13610278.6623338 4552334.72692573,-13610279.1738364 4552332.91809926,-13610280.3442039 4552328.05700473,-13610281.5145713 4552323.1959102,-13610282.6849388 4552318.33481567,-13610283.2041525 4552316.1782734,-13610283.9823919 4552311.23921039,-13610284.7606314 4552306.30014739,-13610285.5388708 4552301.36108439,-13610285.5924503 4552301.02104457,-13610285.7999127 4552296.02535048,-13610286.0073751 4552291.0296564,-13610286.2148375 4552286.03396232,-13610286.2933058 4552284.14444567,-13610285.8921183 4552279.1605668,-13610285.4909309 4552274.17668792,-13610285.0897434 4552269.19280905,-13610284.8957189 4552266.78247762,-13610283.9583587 4552261.87112792,-13610283.0209985 4552256.95977823,-13610282.0836383 4552252.04842853,-13610281.4516401 4552248.73703972,-13610280.2831386 4552243.87549633,-13610279.1146371 4552239.01395293,-13610277.9461355 4552234.15240954,-13610276.777634 4552229.29086614,-13610275.8369132 4552225.37700306,-13610275.780024 4552225.12616149,-13610274.7369433 4552220.2361735,-13610273.6938625 4552215.34618551,-13610272.6507818 4552210.45619751,-13610271.607701 4552205.56620952,-13610270.5646203 4552200.67622153,-13610269.5215395 4552195.78623354,-13610268.4784588 4552190.89624554,-13610267.4353781 4552186.00625755,-13610266.3922973 4552181.11626956,-13610265.3492166 4552176.22628157,-13610264.3061358 4552171.33629358,-13610263.2630551 4552166.44630558,-13610262.7596781 4552164.0864621,-13610261.3009174 4552159.30399231,-13610259.8421567 4552154.52152252,-13610258.383396 4552149.73905274,-13610256.9246354 4552144.95658295,-13610255.4658747 4552140.17411317,-13610255.4150604 4552140.00752138,-13610255.384457 4552139.11457027,-13610255.0517026 4552138.28537024,-13610255.2971803 4552136.56799271,-13610255.2377587 4552134.83417785,-13610255.6577309 4552134.04555781,-13610255.7841571 4552133.16107228,-13610256.8554358 4552131.79651856,-13610257.6708826 4552130.26528004,-13610258.4288992 4552129.79230118,-13610258.9806303 4552129.08952732,-13610260.5906617 4552128.44342849,-13610262.0624786 4552127.52506043,-13610262.9554297 4552127.49445705,-13610263.7846298 4552127.16170256,-13610265.5020073 4552127.40718027,-13610267.2358222 4552127.34775866,-13610268.0244422 4552127.7677309,-13610268.9089277 4552127.89415708,-13610270.2734814 4552128.96543578,-13610271.80472 4552129.78088258,-13610272.2776988 4552130.53889924,-13610272.9804727 4552131.09063029,-13610275.9801575 4552135.09086663,-13610278.9798424 4552139.09110296,-13610281.9795272 4552143.0913393,-13610284.9792121 4552147.09157564,-13610287.978897 4552151.09181198,-13610288.2104727 4552151.40063029,-13610288.7104838 4552152.13295383,-13610291.3440069 4552156.38319572,-13610293.97753 4552160.63343761,-13610296.4804838 4552164.67295383,-13610296.8544499 4552165.3308636,-13610299.1590181 4552169.76808857,-13610301.4635863 4552174.20531354,-13610303.7681545 4552178.64253851,-13610306.0727227 4552183.07976348,-13610308.3772909 4552187.51698845,-13610310.6818591 4552191.95421341,-13610312.9864273 4552196.39143838,-13610315.2909955 4552200.82866335,-13610317.5955637 4552205.26588832,-13610319.9001319 4552209.70311329,-13610320.9844499 4552211.7908636,-13610321.1167911 4552212.05515094,-13610323.2892157 4552216.55854651,-13610325.4616402 4552221.06194208,-13610327.5567911 4552225.40515094,-13610327.6151026 4552225.55420033,-13610327.6423175 4552225.58709678,-13610329.7237691 4552230.13325551,-13610331.8052207 4552234.67941423,-13610333.8866723 4552239.22557296,-13610335.9681239 4552243.77173169,-13610338.0495755 4552248.31789042,-13610340.1310271 4552252.86404915,-13610342.2124787 4552257.41020788,-13610343.5516153 4552260.33505488,-13610346.1020897 4552264.63564558,-13610348.6525641 4552268.93623628,-13610350.0866618 4552271.35440107,-13610353.2227469 4552275.2486238,-13610356.3588319 4552279.14284653,-13610358.5318194 4552281.84114624,-13610362.2416685 4552285.19331267,-13610365.9515176 4552288.5454791,-13610369.6613667 4552291.89764552,-13610370.0081601 4552292.21100306,-13610374.1237098 4552295.05041332,-13610378.2392595 4552297.88982358,-13610382.3548092 4552300.72923384,-13610386.4703589 4552303.56864411,-13610390.5859086 4552306.40805437,-13610394.7014583 4552309.24746463,-13610398.817008 4552312.08687489,-13610401.1864655 4552313.7216169,-13610405.6334818 4552316.00723419,-13610410.080498 4552318.29285148,-13610410.9786065 4552318.75444916,-13610415.6012211 4552320.66008145,-13610420.2238357 4552322.56571375,-13610421.5572873 4552323.11541745,-13610426.2369992 4552324.87618325,-13610430.9167111 4552326.63694905,-13610435.5964231 4552328.39771485,-13610437.8336168 4552329.23947058,-13610442.6763907 4552330.4834726,-13610447.5191646 4552331.72747463,-13610452.3619385 4552332.97147665,-13610457.2047124 4552334.21547868,-13610462.0474863 4552335.4594807,-13610466.8902602 4552336.70348273,-13610470.7480041 4552337.69445222,-13610471.1470477 4552337.80581827,-13610475.9341385 4552339.2493421,-13610480.7212294 4552340.69286592,-13610485.5083203 4552342.13638975,-13610490.2954111 4552343.57991358,-13610495.082502 4552345.02343741,-13610499.8695929 4552346.46696124,-13610504.6566837 4552347.91048506,-13610509.4437746 4552349.35400889,-13610514.2308654 4552350.79753272,-13610519.0179563 4552352.24105655,-13610523.8050472 4552353.68458038,-13610528.592138 4552355.12810421,-13610531.2826403 4552355.93941201,-13610536.0858278 4552357.32843703,-13610540.8890152 4552358.71746205,-13610545.6922026 4552360.10648707,-13610550.4953901 4552361.4955121,-13610555.2985775 4552362.88453712,-13610560.1017649 4552364.27356214,-13610564.9049523 4552365.66258716,-13610569.7081398 4552367.05161218,-13610574.5113272 4552368.4406372,-13610579.3145146 4552369.82966223,-13610584.1177021 4552371.21868725,-13610584.68805 4552371.38362514,-13610585.4766808 4552371.64768827,-13610590.1478366 4552373.43102865,-13610594.8189925 4552375.21436903,-13610598.6960623 4552376.69454554,-13610603.3899666 4552378.41711986,-13610608.0838709 4552380.13969418,-13610608.9071098 4552380.44180732,-13610613.7098027 4552381.83254144,-13610618.5124955 4552383.22327556,-13610623.3151884 4552384.61400967,-13610628.1178812 4552386.00474379,-13610632.9205741 4552387.39547791,-13610634.8514682 4552387.9546143,-13610635.0181249 4552388.00444874,-13610639.7959005 4552389.47851117,-13610644.5736761 4552390.9525736,-13610649.3514517 4552392.42663603,-13610654.1292274 4552393.90069846,-13610658.907003 4552395.37476089,-13610663.6847786 4552396.84882332,-13610668.4625543 4552398.32288574,-13610673.2403299 4552399.79694817,-13610678.0181055 4552401.2710106,-13610682.7958811 4552402.74507303,-13610687.5736568 4552404.21913546,-13610692.3514324 4552405.69319789,-13610697.129208 4552407.16726032,-13610701.9069837 4552408.64132275,-13610702.4681249 4552408.81444874,-13610703.985389 4552409.76793592,-13610705.6383028 4552410.46010933,-13610706.1440027 4552411.12446337,-13610706.8509266 4552411.56871229,-13610707.6881723 4552413.15308847,-13610708.773551 4552414.57898515,-13610708.8793229 4552415.40718255,-13610709.2694126 4552416.14537539,-13610709.2023005 4552417.93610826,-13610709.4293177 4552419.71366034,-13610709.1068201 4552420.48378627,-13610709.0755513 4552421.31812486,-13610708.1220641 4552422.83538899,-13610707.4298907 4552424.48830283,-13610706.7655366 4552424.99400266,-13610706.3212877 4552425.70092665,-13610704.7369115 4552426.53817234,-13610703.3110148 4552427.62355102,-13610702.4828174 4552427.7293229,-13610701.7446246 4552428.11941256,-13610699.9538917 4552428.05230052,-13610698.1763397 4552428.27931768,-13610693.2216808 4552427.60748751,-13610688.267022 4552426.93565734,-13610683.3123631 4552426.26382716,-13610678.3577043 4552425.59199699,-13610673.4030455 4552424.92016682,-13610668.4483866 4552424.24833665,-13610663.4937278 4552423.57650648,-13610658.5390689 4552422.90467631,-13610653.5844101 4552422.23284613,-13610648.6297513 4552421.56101596,-13610643.6750924 4552420.88918579,-13610638.7204336 4552420.21735562,-13610633.7657747 4552419.54552544,-13610628.8111159 4552418.87369527,-13610628.3363397 4552418.80931768,-13610627.7692016 4552418.71574499,-13610622.8613291 4552417.76034581,-13610617.9534567 4552416.80494663,-13610613.0455842 4552415.84954745,-13610608.1377117 4552414.89414827,-13610603.2298392 4552413.93874909,-13610598.3219667 4552412.98334992,-13610594.0192016 4552412.14574499,-13610593.0824608 4552411.91600649,-13610588.2894575 4552410.49223689,-13610583.4964543 4552409.06846728,-13610578.7034511 4552407.64469767,-13610573.9104478 4552406.22092807,-13610569.1174446 4552404.79715846,-13610564.3244413 4552403.37338885,-13610559.5314381 4552401.94961925,-13610554.7384348 4552400.52584964,-13610549.9454316 4552399.10208004,-13610545.1524283 4552397.67831043,-13610540.3594251 4552396.25454082,-13610535.5664218 4552394.83077122,-13610530.7734186 4552393.40700161,-13610525.9804153 4552391.98323201,-13610521.1874121 4552390.5594624,-13610516.3944088 4552389.13569279,-13610511.6014056 4552387.71192319,-13610506.8084024 4552386.28815358,-13610502.0153991 4552384.86438398,-13610497.2223959 4552383.44061437,-13610492.4293926 4552382.01684476,-13610487.6363894 4552380.59307516,-13610482.8433861 4552379.16930555,-13610478.0503829 4552377.74553595,-13610473.2573796 4552376.32176634,-13610468.4643764 4552374.89799673,-13610463.6713731 4552373.47422713,-13610458.8783699 4552372.05045752,-13610454.0853667 4552370.62668792,-13610453.9387501 4552370.58313523,-13610449.0062496 4552369.76433227,-13610444.073749 4552368.9455293,-13610442.5360477 4552368.69026842,-13610437.5451831 4552368.38815798,-13610432.5543185 4552368.08604753,-13610431.6801355 4552368.03313089,-13610426.7305234 4552368.74118473,-13610421.7809114 4552369.44923858,-13610416.8312993 4552370.15729243,-13610411.8816872 4552370.86534627,-13610411.1813072 4552370.96553731,-13610406.315235 4552372.11503355,-13610401.4491628 4552373.2645298,-13610396.5830906 4552374.41402604,-13610391.7170185 4552375.56352228,-13610387.0467397 4552376.66676688,-13610382.3795902 4552378.46056615,-13610377.7124408 4552380.25436542,-13610373.0452913 4552382.04816469,-13610368.3781418 4552383.84196396,-13610363.7109924 4552385.63576323,-13610362.6998188 4552386.02440353,-13610358.3535767 4552388.49628119,-13610354.0073345 4552390.96815884,-13610349.6610923 4552393.44003649,-13610345.3148502 4552395.91191414,-13610341.3310727 4552398.177644,-13610337.5217727 4552401.41635264,-13610333.7124727 4552404.65506128,-13610329.9031727 4552407.89376991,-13610326.0938727 4552411.13247855,-13610323.9155967 4552412.98447277,-13610320.8911763 4552416.9660405,-13610317.866756 4552420.94760823,-13610314.8423356 4552424.92917596,-13610311.8179153 4552428.91074368,-13610310.3065952 4552430.90035582,-13610307.7806991 4552435.21542817,-13610305.2548031 4552439.53050051,-13610302.7289071 4552443.84557286,-13610300.2030111 4552448.16064521,-13610298.7141582 4552450.70410226,-13610296.3680173 4552455.11948706,-13610294.0218764 4552459.53487185,-13610291.6757355 4552463.95025664,-13610289.3295946 4552468.36564143,-13610286.9834537 4552472.78102622,-13610286.363435 4552473.94788758,-13610284.1934496 4552478.45245898,-13610282.0234642 4552482.95703038,-13610279.8534789 4552487.46160178,-13610277.6834935 4552491.96617318,-13610275.5135081 4552496.47074458,-13610273.3435228 4552500.97531598,-13610271.1735374 4552505.47988738,-13610271.0863442 4552505.66088769,-13610269.9026606 4552510.51875689,-13610268.718977 4552515.37662609,-13610268.3557384 4552516.86736717,-13610268.2925941 4552517.11293476,-13610266.9861267 4552521.93923179,-13610265.6796593 4552526.76552881,-13610265.3825941 4552527.86293476,-13610265.3694996 4552527.91083588,-13610264.0390817 4552532.73058568,-13610262.7086637 4552537.55033548,-13610261.3782458 4552542.37008527,-13610260.0478278 4552547.18983507,-13610258.7174099 4552552.00958487,-13610257.3869919 4552556.82933466,-13610256.056574 4552561.64908446,-13610254.7261561 4552566.46883426,-13610253.3957381 4552571.28858405,-13610252.0653202 4552576.10833385,-13610251.0294996 4552579.86083588,-13610248.4969715 4552584.17201919,-13610248.4076336 4552584.32410127,-13610244.0588083 4552586.79143148,-13610243.9053983 4552586.87846947,-13610238.90554 4552586.84082746,-13610238.7291641 4552586.83949959,-13610234.4179808 4552584.3069715,-13610234.2658987 4552584.21763359,-13610231.7985685 4552579.86880827,-13610231.7115305 4552579.71539833,-13610231.7491725 4552574.71554002,-13610231.7505004 4552574.53916412,-13610233.0809183 4552569.71941432,-13610234.4113363 4552564.89966452,-13610235.7417542 4552560.07991473,-13610237.0721722 4552555.26016493,-13610238.4025901 4552550.44041513,-13610239.7330081 4552545.62066534,-13610241.063426 4552540.80091554,-13610242.3938439 4552535.98116574,-13610243.7242619 4552531.16141595,-13610245.0546798 4552526.34166615,-13610246.0838937 4552522.61309836,-13610247.3903611 4552517.78680133,-13610248.6968285 4552512.96050431,-13610248.954277 4552512.00944873,-13610250.1379606 4552507.15157953,-13610251.3216442 4552502.29371033,-13610251.9042616 4552499.90263283,-13610251.9075748 4552499.89338323,-13610251.9074899 4552499.88942268,-13610253.0977786 4552495.03316765,-13610254.2880673 4552490.17691262,-13610255.3911957 4552485.6762624,-13610254.0568314 4552490.49492113,-13610252.7224671 4552495.31357985,-13610251.3881027 4552500.13223857,-13610250.0537384 4552504.95089729,-13610248.7193741 4552509.76955602,-13610247.8473174 4552512.91872862,-13610247.8460407 4552512.9233351,-13610246.5093731 4552517.74135542,-13610245.1727056 4552522.55937575,-13610244.7380731 4552524.12600924,-13610243.4087324 4552528.94605626,-13610242.0793916 4552533.76610328,-13610240.7500509 4552538.5861503,-13610239.4207102 4552543.40619731,-13610238.0913695 4552548.22624433,-13610236.7620288 4552553.04629135,-13610235.432688 4552557.86633837,-13610234.1033473 4552562.68638538,-13610233.540094 4552564.72868144,-13610231.0085295 4552569.04043064,-13610230.9192256 4552569.19253268,-13610226.5709518 4552571.66083478,-13610226.4175614 4552571.74790705,-13610221.4176948 4552571.71138248,-13610221.2413186 4552571.71009404,-13610216.9295694 4552569.17852954,-13610216.7774673 4552569.08922561,-13610214.3091652 4552564.74095184,-13610214.222093 4552564.58756135,-13610214.2586175 4552559.58769476,-13610214.259906 4552559.41131856,-13610215.5892467 4552554.59127154,-13610216.9185874 4552549.77122453,-13610218.2479281 4552544.95117751,-13610219.5772688 4552540.13113049,-13610220.9066096 4552535.31108347,-13610222.2359503 4552530.49103646,-13610223.565291 4552525.67098944,-13610224.8946317 4552520.85094242,-13610225.459906 4552518.80131856,-13610225.4639593 4552518.7866649,-13610226.8006269 4552513.96864458,-13610228.1372944 4552509.15062425,-13610228.5733203 4552507.57896842,-13610229.9076846 4552502.7603097,-13610231.2420489 4552497.94165097,-13610232.5764132 4552493.12299225,-13610233.9107775 4552488.30433353,-13610235.2451418 4552483.48567481,-13610236.5795062 4552478.66701608,-13610237.9138705 4552473.84835736,-13610239.2482348 4552469.02969864,-13610240.5825991 4552464.21103991,-13610241.9169634 4552459.39238119,-13610243.2513277 4552454.57372247,-13610244.585692 4552449.75506375,-13610245.9200563 4552444.93640502,-13610246.9626826 4552441.17127138,-13610247.0763818 4552440.87292091),(-13610305.4813313 4552273.25376348,-13610305.8825187 4552278.23764235,-13610306.2777578 4552283.14762512,-13610306.3013882 4552284.36492476,-13610306.0939258 4552289.36061884,-13610305.8864634 4552294.35631292,-13610305.679001 4552299.352007,-13610305.5513882 4552302.42492476,-13610305.438126 4552303.56647891,-13610304.6598866 4552308.50554192,-13610303.8816471 4552313.44460492,-13610303.1034076 4552318.38366792,-13610302.898126 4552319.68647891,-13610302.7421891 4552320.4707349,-13610301.5718216 4552325.33182943,-13610300.4014542 4552330.19292396,-13610299.2310867 4552335.05401849,-13610298.5721891 4552337.7907349,-13610298.4726588 4552338.17110949,-13610297.1121041 4552342.98243891,-13610295.7515494 4552347.79376833,-13610294.4999474 4552352.21980797,-13610296.1423623 4552347.4972585,-13610297.7847771 4552342.77470904,-13610299.4271919 4552338.05215957,-13610301.0696068 4552333.3296101,-13610302.7120216 4552328.60706063,-13610304.3544365 4552323.88451116,-13610305.9968513 4552319.16196169,-13610307.6392661 4552314.43941222,-13610309.0156508 4552310.48179777,-13610310.3992043 4552305.67703142,-13610311.7827579 4552300.87226508,-13610312.8401668 4552297.20012453,-13610313.7306427 4552292.2800582,-13610314.4608297 4552288.24562171,-13610311.8916371 4552283.95618709,-13610309.3224445 4552279.66675247,-13610306.7532519 4552275.37731786,-13610305.4813313 4552273.25376348),(-13610331.1812635 4552305.78332423,-13610329.7977099 4552310.58809058,-13610328.4141564 4552315.39285692,-13610328.1595327 4552316.27710706,-13610327.9950989 4552316.79482968,-13610326.3526841 4552321.51737915,-13610324.7102693 4552326.23992862,-13610323.0678544 4552330.96247809,-13610321.4254396 4552335.68502756,-13610319.7830247 4552340.40757703,-13610318.1406099 4552345.1301265,-13610316.4981951 4552349.85267597,-13610314.8557802 4552354.57522543,-13610313.2133654 4552359.2977749,-13610311.6160078 4552363.89076811,-13610316.1455467 4552361.77339293,-13610317.7552496 4552361.02092226,-13610318.3163896 4552360.77921581,-13610322.9667817 4552358.94241061,-13610327.6171738 4552357.1056054,-13610332.2675659 4552355.26880019,-13610334.6463896 4552354.32921581,-13610334.874691 4552354.24225021,-13610339.5685659 4552352.51959573,-13610344.2624408 4552350.79694125,-13610348.9563157 4552349.07428677,-13610353.6501906 4552347.35163229,-13610358.3440655 4552345.62897782,-13610363.0379404 4552343.90632334,-13610367.7318153 4552342.18366886,-13610372.4256902 4552340.46101438,-13610375.5838495 4552339.30196832,-13610371.4652236 4552336.46702195,-13610367.3465977 4552333.63207558,-13610363.2279719 4552330.79712921,-13610359.109346 4552327.96218284,-13610354.9907201 4552325.12723647,-13610350.8720943 4552322.2922901,-13610347.9301073 4552320.26725174,-13610347.0371076 4552319.57509399,-13610343.2645606 4552316.29364779,-13610339.4920136 4552313.01220158,-13610335.7194666 4552309.73075538,-13610331.9469196 4552306.44930918,-13610331.1812635 4552305.78332423),(-13610302.9461193 4552391.94821479,-13610301.4991214 4552396.7342567,-13610300.0521236 4552401.52029861,-13610298.6051257 4552406.30634053,-13610297.1581279 4552411.09238244,-13610295.71113 4552415.87842435,-13610295.122368 4552417.82579379,-13610298.1467884 4552413.84422606,-13610301.1712087 4552409.86265833,-13610304.1956291 4552405.88109061,-13610307.2200494 4552401.89952288,-13610308.6468645 4552400.02115931,-13610310.1325827 4552398.45140003,-13610313.9418827 4552395.2126914,-13610317.7511827 4552391.97398276,-13610321.5604827 4552388.73527412,-13610325.3697827 4552385.49656549,-13610329.0925827 4552382.33140003,-13610330.6262447 4552381.25751569,-13610334.9724868 4552378.78563804,-13610339.318729 4552376.31376038,-13610343.6649712 4552373.84188273,-13610348.0112133 4552371.37000508,-13610351.205969 4552369.55302275,-13610346.5120941 4552371.27567723,-13610341.8799908 4552372.97566148,-13610337.2295987 4552374.81246669,-13610332.5792067 4552376.6492719,-13610327.9288146 4552378.4860771,-13610325.9478741 4552379.26850613,-13610321.4183352 4552381.38588131,-13610316.8887963 4552383.50325649,-13610312.3592575 4552385.62063167,-13610311.0486422 4552386.23329101,-13610306.962733 4552389.11519083,-13610302.9461193 4552391.94821479),(-13610396.215337 4552353.03456179,-13610391.5214621 4552354.75721626,-13610389.2117785 4552355.6048713,-13610394.0778507 4552354.45537506,-13610397.3197688 4552353.6895474,-13610396.215337 4552353.03456179))'

# bzcat uptown.osm.bz2 | python osm-slurp.py -
#wkt = 'POLYGON((-13610544.5178097337484360 4552119.1998063679784536, -13610544.5091468710452318 4552119.2175315553322434, -13610540.4626833815127611 4552127.4867085786536336, -13610536.4162198919802904 4552135.7558856019750237, -13610532.3697564024478197 4552144.0250626252964139, -13610528.3232929129153490 4552152.2942396486178041, -13610524.2768294233828783 4552160.5634166719391942, -13610520.2303659338504076 4552168.8325936952605844, -13610516.1839024443179369 4552177.1017707185819745, -13610512.1374389547854662 4552185.3709477419033647, -13610508.0909754652529955 4552193.6401247652247548, -13610504.0445119757205248 4552201.9093017885461450, -13610504.0437397118657827 4552201.9108797619119287, -13610499.8437113780528307 4552210.4919659309089184, -13610495.6436830442398787 4552219.0730520999059081, -13610491.4436547104269266 4552227.6541382689028978, -13610487.2436263766139746 4552236.2352244378998876, -13610483.0435980428010225 4552244.8163106068968773, -13610478.8435697089880705 4552253.3973967758938670, -13610474.6435413751751184 4552261.9784829448908567, -13610470.4435130413621664 4552270.5595691138878465, -13610466.2434847075492144 4552279.1406552828848362, -13610462.0434563737362623 4552287.7217414518818259, -13610457.8434280399233103 4552296.3028276208788157, -13610453.6433997061103582 4552304.8839137898758054, -13610449.4433713722974062 4552313.4649999588727951, -13610445.2433430384844542 4552322.0460861278697848, -13610441.0433147046715021 4552330.6271722968667746, -13610436.8432863708585501 4552339.2082584658637643, -13610438.7224836964160204 4552339.4341530818492174, -13610442.8644216675311327 4552342.5388703122735023, -13610447.0063596386462450 4552345.6435875426977873, -13610449.0410245284438133 4552350.4033205220475793, -13610451.0756894163787365 4552355.1630535013973713, -13610450.4578944090753794 4552360.3024356216192245, -13610449.8400994017720222 4552365.4418177418410778, -13610446.7353821694850922 4552369.5837557129561901, -13610443.6306649371981621 4552373.7256936840713024, -13610438.8709319587796926 4552375.7603585720062256, -13610434.1111989803612232 4552377.7950234599411488, -13610427.0904882680624723 4552378.7999045485630631, -13610420.0697775557637215 4552379.8047856371849775, -13610413.0490668434649706 4552380.8096667258068919, -13610405.3699217382818460 4552382.6240505613386631, -13610397.6907766330987215 4552384.4384343968704343, -13610390.0116315279155970 4552386.2528182324022055, -13610382.3397599775344133 4552389.1991926198825240, -13610374.6678884271532297 4552392.1455670073628426, -13610366.9960168767720461 4552395.0919413948431611, -13610360.3634389191865921 4552398.8639490641653538, -13610353.7308609616011381 4552402.6359567334875464, -13610347.0982830040156841 4552406.4079644028097391, -13610341.8090477809309959 4552410.9051571842283010, -13610336.5198125578463078 4552415.4023499656468630, -13610331.2305773347616196 4552419.8995427470654249, -13610327.0353229437023401 4552425.4237432749941945, -13610322.8400685526430607 4552430.9479438029229641, -13610318.6448141615837812 4552436.4721443308517337, -13610314.9159562774002552 4552442.8424295773729682, -13610311.1870983932167292 4552449.2127148238942027, -13610307.4582405090332031 4552455.5830000704154372, -13610303.4026783537119627 4552463.2122473679482937, -13610299.3471161983907223 4552470.8414946654811502, -13610295.2915540430694818 4552478.4707419630140066, -13610291.6082452945411205 4552486.1183783989399672, -13610287.9249365478754044 4552493.7660148348659277, -13610284.2416278012096882 4552501.4136512707918882, -13610280.5583190545439720 4552509.0612877067178488, -13610279.3158876709640026 4552514.1545870127156377, -13610278.0734562873840332 4552519.2478863187134266, -13610277.9505353234708309 4552519.7260794742032886, -13610276.4978159684687853 4552525.1014460604637861, -13610275.0450966134667397 4552530.4768126467242837, -13610275.0169561170041561 4552530.5798452673479915, -13610272.6272977143526077 4552539.2382272342219949, -13610270.2376393117010593 4552547.8966092010959983, -13610267.8479809090495110 4552556.5549911679700017, -13610265.4583225063979626 4552565.2133731348440051, -13610263.0686641037464142 4552573.8717551017180085, -13610260.6790057010948658 4552582.5301370685920119, -13610260.6606512889266014 4552582.5613849535584450, -13610260.6602529324591160 4552582.5976224485784769, -13610258.0585574042052031 4552591.8971574241295457, -13610255.4568618759512901 4552601.1966923996806145, -13610252.8551663476973772 4552610.4962273752316833, -13610250.2534708194434643 4552619.7957623507827520, -13610247.6517752911895514 4552629.0952973263338208, -13610245.0500797629356384 4552638.3948323018848896, -13610242.4483842346817255 4552647.6943672774359584, -13610242.4385592117905617 4552647.7293633855879307, -13610239.7842077985405922 4552657.1510813375934958, -13610237.1298563852906227 4552666.5727992895990610, -13610234.4755049720406532 4552675.9945172416046262, -13610231.8211535587906837 4552685.4162351936101913, -13610229.1668021455407143 4552694.8379531456157565, -13610226.5124507322907448 4552704.2596710976213217, -13610223.8580993190407753 4552713.6813890496268868, -13610221.2037479057908058 4552723.1031070016324520, -13610218.5493964925408363 4552732.5248249536380172, -13610218.2732935994863510 4552733.4233951438218355, -13610216.0840102806687355 4552739.9942075153812766, -13610213.8947269618511200 4552746.5650198869407177, -13610211.7054436430335045 4552753.1358322585001588, -13610211.5117952674627304 4552753.6898025199770927, -13610209.0944398995488882 4552760.2925240881741047, -13610206.6770845316350460 4552766.8952456563711166, -13610204.2597291637212038 4552773.4979672245681286, -13610201.5831366311758757 4552781.9368446916341782, -13610198.9065440986305475 4552790.3757221587002277, -13610196.2299515660852194 4552798.8145996257662773, -13610193.5533590335398912 4552807.2534770928323269, -13610190.8767665009945631 4552815.6923545598983765, -13610188.2001739684492350 4552824.1312320269644260, -13610185.5235814359039068 4552832.5701094940304756, -13610185.3467917963862419 4552833.1015599370002747, -13610182.3602488860487938 4552841.6766592226922512, -13610179.3737059757113457 4552850.2517585083842278, -13610176.3871630653738976 4552858.8268577940762043, -13610173.4006201550364494 4552867.4019570797681808, -13610170.4140772446990013 4552875.9770563654601574, -13610167.4275343343615532 4552884.5521556511521339, -13610164.4409914240241051 4552893.1272549368441105, -13610161.5312657244503498 4552897.4084248226135969, -13610158.6215400248765945 4552901.6895947083830833, -13610153.9610587060451508 4552903.9423337345942855, -13610149.3005773872137070 4552906.1950727608054876, -13610144.7191497664898634 4552905.8584529543295503, -13610144.0950340032577515 4552907.6059908261522651, -13610141.1516676917672157 4552911.8641023803502321, -13610138.2083013802766800 4552916.1222139345481992, -13610133.5302156060934067 4552918.3381635574623942, -13610128.8521298319101334 4552920.5541131803765893, -13610123.6928138993680477 4552920.1341389603912830, -13610118.5334979668259621 4552919.7141647404059768, -13610114.2753864116966724 4552916.7707984298467636, -13610110.0172748565673828 4552913.8274321202188730, -13610107.8013252355158329 4552909.1493463460355997, -13610105.5853756144642830 4552904.4712605718523264, -13610106.0053498335182667 4552899.3119446393102407, -13610106.4253240525722504 4552894.1526287067681551, -13610109.7737230546772480 4552884.7770378282293677, -13610113.1221220567822456 4552875.4014469496905804, -13610116.4705210588872433 4552866.0258560711517930, -13610119.8189200609922409 4552856.6502651926130056, -13610122.6020113378763199 4552848.5339341098442674, -13610125.3851026147603989 4552840.4176030270755291, -13610128.1681938916444778 4552832.3012719443067908, -13610130.9512851685285568 4552824.1849408615380526, -13610133.7343764454126358 4552816.0686097787693143, -13610136.6855542156845331 4552806.8194269593805075, -13610139.2419097125530243 4552798.8048698361963034, -13610141.7982652094215155 4552790.7903127130120993, -13610144.3546207062900066 4552782.7757555898278952, -13610146.9109762031584978 4552774.7611984666436911, -13610149.4673317000269890 4552766.7466413434594870, -13610152.0236871968954802 4552758.7320842202752829, -13610154.8471252098679543 4552749.1421542009338737, -13610157.6705632209777832 4552739.5522241815924644, -13610159.4453708417713642 4552733.0499894162639976, -13610161.2201784625649452 4552726.5477546509355307, -13610162.9949860833585262 4552720.0455198856070638, -13610163.0389783978462219 4552719.8869202891364694, -13610164.5891182161867619 4552714.3863840363919735, -13610166.1392580345273018 4552708.8858477845788002, -13610167.2364469170570374 4552703.6617212016135454, -13610168.3336357995867729 4552698.4375946186482906, -13610169.6402287278324366 4552691.3902519475668669, -13610170.9468216560781002 4552684.3429092764854431, -13610172.2534145843237638 4552677.2955666054040194, -13610172.3449912648648024 4552676.8322236053645611, -13610174.0370475240051746 4552668.7725808471441269, -13610175.7291037831455469 4552660.7129380889236927, -13610177.4211600422859192 4552652.6532953307032585, -13610177.7430809438228607 4552651.3418074864894152, -13610180.3368250802159309 4552642.1303109824657440, -13610182.9305692166090012 4552632.9188144784420729, -13610185.5243133530020714 4552623.7073179744184017, -13610188.1180574893951416 4552614.4958214703947306, -13610188.1403893623501062 4552614.4171286057680845, -13610190.4998230040073395 4552606.1672525899484754, -13610192.8592566456645727 4552597.9173765741288662, -13610195.2186902873218060 4552589.6675005583092570, -13610197.5781239289790392 4552581.4176245424896479, -13610199.9375575706362724 4552573.1677485266700387, -13610202.2969912122935057 4552564.9178725108504295, -13610204.6564248539507389 4552556.6679964950308204, -13610206.8911375422030687 4552548.5647147661074996, -13610209.1258502304553986 4552540.4614330371841788, -13610211.3605629187077284 4552532.3581513082608581, -13610213.5952756069600582 4552524.2548695793375373, -13610215.8299882952123880 4552516.1515878504142165, -13610215.8356199301779270 4552516.1312090381979942, -13610217.3885268270969391 4552510.5233582556247711, -13610218.9414337240159512 4552504.9155074730515480, -13610218.9415067043155432 4552504.9152439264580607, -13610221.5686466880142689 4552495.4286315245553851, -13610224.1957866717129946 4552485.9420191226527095, -13610226.8229266554117203 4552476.4554067207500339, -13610229.4500666391104460 4552466.9687943188473582, -13610232.0772066228091717 4552457.4821819169446826, -13610234.7043466065078974 4552447.9955695150420070, -13610237.3314865902066231 4552438.5089571131393313, -13610238.6689711641520262 4552435.0001422474160790, -13610242.7376985512673855 4552426.7504721442237496, -13610246.8064259402453899 4552418.5008020410314202, -13610250.8751533292233944 4552410.2511319378390908, -13610254.9438807182013988 4552402.0014618346467614, -13610256.4947393406182528 4552399.3810134669765830, -13610261.1979878265410662 4552392.6601187493652105, -13610265.9012363124638796 4552385.9392240317538381, -13610268.4166475255042315 4552382.9978588875383139, -13610274.4612958766520023 4552377.1787264496088028, -13610280.5059442259371281 4552371.3595940116792917, -13610282.8476743865758181 4552369.4253558786585927, -13610288.6696837563067675 4552365.3181513100862503, -13610294.4916931260377169 4552361.2109467415139079, -13610297.5510053317993879 4552359.4355093324556947, -13610305.5381787959486246 4552355.7016898095607758, -13610313.5253522600978613 4552351.9678702875971794, -13610314.6449994705617428 4552351.4854784896597266, -13610322.8102841190993786 4552348.2588969860225916, -13610330.9755687676370144 4552345.0323154814541340, -13610331.4368251301348209 4552344.8565952964127064, -13610339.8525786343961954 4552341.7689038738608360, -13610348.2683321386575699 4552338.6812124513089657, -13610356.6840856429189444 4552335.5935210287570953, -13610365.0998391471803188 4552332.5058296062052250, -13610373.5155926514416933 4552329.4181381836533546, -13610381.9313461557030678 4552326.3304467611014843, -13610390.3470996599644423 4552323.2427553385496140, -13610392.1761380396783352 4552322.6695278473198414, -13610401.2820723857730627 4552320.2883448349311948, -13610401.5992495808750391 4552320.2273704912513494, -13610405.7565442100167274 4552311.7335936389863491, -13610409.9138388391584158 4552303.2398167867213488, -13610414.0711334683001041 4552294.7460399344563484, -13610418.2284280974417925 4552286.2522630821913481, -13610422.3857227265834808 4552277.7584862299263477, -13610426.5430173557251692 4552269.2647093776613474, -13610430.7003119848668575 4552260.7709325253963470, -13610434.8576066140085459 4552252.2771556731313467, -13610439.0149012431502342 4552243.7833788208663464, -13610443.1721958722919226 4552235.2896019686013460, -13610447.3294905014336109 4552226.7958251163363457, -13610451.4867851305752993 4552218.3020482640713453, -13610455.6440797597169876 4552209.8082714118063450, -13610459.8013743888586760 4552201.3144945595413446, -13610463.9586690180003643 4552192.8207177072763443, -13610468.1159636471420527 4552184.3269408550113440, -13610472.1619548834860325 4552176.0587289063259959, -13610476.2079461216926575 4552167.7905169576406479, -13610480.2539373598992825 4552159.5223050089552999, -13610484.2999285981059074 4552151.2540930602699518, -13610488.3459198363125324 4552142.9858811115846038, -13610492.3919110745191574 4552134.7176691628992558, -13610496.4379023127257824 4552126.4494572142139077, -13610500.4838935509324074 4552118.1812452655285597, -13610504.5298847891390324 4552109.9130333168432117, -13610508.5758760273456573 4552101.6448213681578636, -13610512.9282277356833220 4552092.7282766932621598, -13610517.2805794440209866 4552083.8117320183664560, -13610521.6329311523586512 4552074.8951873434707522, -13610525.9852828606963158 4552065.9786426685750484, -13610530.3376345690339804 4552057.0620979936793447, -13610534.6899862773716450 4552048.1455533187836409, -13610539.0423379857093096 4552039.2290086438879371, -13610543.3946896940469742 4552030.3124639689922333, -13610547.7470414023846388 4552021.3959192940965295, -13610552.0993931107223034 4552012.4793746192008257, -13610556.4517448190599680 4552003.5628299443051219, -13610560.8040965273976326 4551994.6462852694094181, -13610565.1564482357352972 4551985.7297405945137143, -13610569.5087999440729618 4551976.8131959196180105, -13610573.8611516524106264 4551967.8966512447223067, -13610578.2135033607482910 4551958.9801065698266029, -13610582.5658550690859556 4551950.0635618949308991, -13610586.9182067774236202 4551941.1470172200351954, -13610590.3154432903975248 4551937.2414182545617223, -13610593.7126798033714294 4551933.3358192890882492, -13610598.6075724139809608 4551931.6520896274596453, -13610603.5024650245904922 4551929.9683599658310413, -13610608.5834312047809362 4551930.9576536100357771, -13610613.6643973849713802 4551931.9469472542405128, -13610617.5699963495135307 4551935.3441837728023529, -13610621.4755953140556812 4551938.7414202913641930, -13610623.1593249775469303 4551943.6363129010424018, -13610624.8430546410381794 4551948.5312055107206106, -13610623.8537609968334436 4551953.6121716909110546, -13610622.8644673526287079 4551958.6931378711014986, -13610618.5118752624839544 4551967.6101750098168850, -13610614.1592831723392010 4551976.5272121485322714, -13610609.8066910821944475 4551985.4442492872476578, -13610605.4540989920496941 4551994.3612864259630442, -13610601.1015069019049406 4552003.2783235646784306, -13610596.7489148117601871 4552012.1953607033938169, -13610592.3963227216154337 4552021.1123978421092033, -13610588.0437306314706802 4552030.0294349808245897, -13610583.6911385413259268 4552038.9464721195399761, -13610579.3385464511811733 4552047.8635092582553625, -13610574.9859543610364199 4552056.7805463969707489, -13610570.6333622708916664 4552065.6975835356861353, -13610566.2807701807469130 4552074.6146206744015217, -13610561.9281780906021595 4552083.5316578131169081, -13610557.5755860004574060 4552092.4486949518322945, -13610553.2229939103126526 4552101.3657320905476809, -13610548.8704018201678991 4552110.2827692292630672, -13610544.5178097300231457 4552119.1998063679784536, -13610544.5178097337484360 4552119.1998063679784536))'

polygon = loads(wkt)

img = ImageSurface(FORMAT_RGB24, 900, 900)
ctx = Context(img)

ctx.move_to(0, 0)
ctx.line_to(900, 0)
ctx.line_to(900, 900)
ctx.line_to(0, 900)
ctx.line_to(0, 0)

ctx.set_source_rgb(1, 1, 1)
ctx.fill()

xmin, ymax, xmax, ymin = polygon.bounds

size = max(abs(xmax - xmin), abs(ymax - ymin))

def tx(x):
    return 50 + (x - xmin) * 800 / size

def ty(y):
    return 50 + (y - ymin) * 800 / -size

for geom in (hasattr(polygon, 'geoms') and polygon.geoms or [polygon]):
    points = list(geom.exterior.coords)
    
    if hasattr(geom, 'interiors'):
        for geom in geom.interiors:
            points += list(geom.coords)

for (x, y) in points:
    ctx.arc(tx(x), ty(y), 2, 0, 2*pi)
    ctx.set_source_rgb(.6, .6, .6)
    ctx.fill()

print 'qhull...'

rbox = '\n'.join( ['2', str(len(points))] + ['%.2f %.2f' % (x, y) for (x, y) in points] + [''] )

qhull = Popen('qvoronoi o'.split(), stdin=PIPE, stdout=PIPE)
qhull.stdin.write(rbox)
qhull.stdin.close()
sleep(1) # qhull.wait()
qhull = qhull.stdout.read().splitlines()

vert_count, poly_count = map(int, qhull[1].split()[:2])

print 'graph...'

skeleton = Graph()

for (index, line) in enumerate(qhull[2:2+vert_count]):
    point = Point(*map(float, line.split()[:2]))
    if point.within(polygon):
        skeleton.add_node(index, dict(point=point))

for line in qhull[2 + vert_count:2 + vert_count + poly_count]:
    indexes = map(int, line.split()[1:])
    for (v, w) in zip(indexes, indexes[1:] + indexes[:1]):
        if v not in skeleton.node or w not in skeleton.node:
            continue
        v1, v2 = skeleton.node[v]['point'], skeleton.node[w]['point']
        line = LineString([(v1.x, v1.y), (v2.x, v2.y)])
        if line.within(polygon):
            skeleton.add_edge(v, w, dict(line=line, length=line.length))

print 'trim...'

removing = True

while removing:
    removing = False

    for index in skeleton.nodes():
        if skeleton.degree(index) == 1:
            depth = skeleton.node[index].get('depth', 0)
            if depth < 10:
                other = skeleton.neighbors(index)[0]
                skeleton.node[other]['depth'] = depth + skeleton.edge[index][other]['line'].length
                skeleton.remove_node(index)
                removing = True

print 'draw...'

for index in skeleton.nodes():
    point = skeleton.node[index]['point']

    if skeleton.degree(index) == 1:
        ctx.arc(tx(point.x), ty(point.y), 3, 0, 2*pi)
        ctx.set_source_rgb(.8, 0, 0)
        ctx.fill()

for (v, w) in skeleton.edges():
    (x1, y1), (x2, y2) = skeleton.edge[v][w]['line'].coords
    
    ctx.move_to(tx(x1), ty(y1))
    ctx.line_to(tx(x2), ty(y2))
    ctx.set_source_rgb(0, 0, 0)
    ctx.set_line_width(1)
    ctx.stroke()

img.write_to_png('look.png')

########NEW FILE########

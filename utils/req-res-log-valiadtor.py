#!/usr/bin/env python3
import os
import glob
import json
import jsonschema
import subprocess
import redis
import time


class Request(object):
    def __init__(self, f):
        self.argv = []
        while True:
            line = f.readline()
            if not line:
                break
            length = int(line)
            arg = str(f.read(length))
            f.read(2)  # read \r\n
            if arg == "__argv_end__":
                break
            self.argv.append(arg)

    def command(self):
        return self.argv[0].lower() if self.argv else None

    def __str__(self):
        return json.dumps(self.argv)


class Response(object):
    def __init__(self, f):
        self.error = False

        line = f.readline()[:-2]
        if line[0] == '+':
            self.json = line[1:]
        elif line[0] == '-':
            self.json = line[1:]
            self.error = True
        elif line[0] == '$':
            self.json = str(f.read(int(line[1:])))
            f.read(2)  # read \r\n
        elif line[0] == ':':
            self.json = int(line[1:])
        elif line[0] == '_':
            self.json = None
        elif line[0] == '#':
            self.json = line[1] == 't'
        elif line[0] == '!':
            self.json = str(f.read(int(line[1:])))
            f.read(2)  # read \r\n
            self.error = True
        elif line[0] == '=':
            self.json = str(f.read(int(line[1:])))[4:]   # skip "txt:" or "mkd:"
            f.read(2)  # read \r\n
        elif line[0] == '(':
            self.json = long(line[1:])
        elif line[0] in ['*', '~']:  # unfortunately JSON doesn't tell the difference between a list and a set
            self.json = []
            count = int(line[1:])
            for i in range(count):
                ele = Response(f)
                self.json.append(ele.json)
        elif line[0] == '%':
            self.json = {}
            count = int(line[1:])
            for i in range(count):
                field = Response(f)
                assert isinstance(field.json, str)
                value = Response(f)
                self.json[str(field)] = value.json

    def __str__(self):
        return json.dumps(self.json)

        
# Figure out where the sources are
srcdir = os.path.abspath(os.path.dirname(os.path.abspath(__file__)) + "/../src")
testdir = os.path.abspath(os.path.dirname(os.path.abspath(__file__)) + "/../tests")

if __name__ == '__main__':
    print('Starting Redis server')
    redis_proc = subprocess.Popen(['%s/redis-server' % srcdir, '--port', '6534'], stdout=subprocess.PIPE)
    
    while True:
        try:
            print('Connecting to Redis...')
            r = redis.Redis(port=6534)
            r.ping()
            break
        except Exception as e:
            time.sleep(0.1)
            pass

    cli_proc = subprocess.Popen(['%s/redis-cli' % srcdir, '-p', '6534', '--json', 'command', 'docs'], stdout=subprocess.PIPE)
    stdout, stderr = cli_proc.communicate()
    docs = json.loads(stdout)

    redis_proc.terminate()
    redis_proc.wait()

    # Create all command objects
    print("Processing files...")
    for filename in glob.glob('%s/tmp/*/*.reqres' % testdir):
        with open(filename, "r", newline="\r\n", encoding="latin-1") as f:
            print("Processing %s..." % filename)
            while True:
                try:
                    req = Request(f)
                    if not req.command():
                        break
                    res = Response(f)
                except json.decoder.JSONDecodeError as err:
                   print("Error processing %s: %s" % (filename, err))
                   exit(1)

                if res.error:
                    continue

                if 'reply_schema' in docs[req.command()]:
                    schema = docs[req.command()]['reply_schema']
                    try:
                        jsonschema.validate(instance=res.json, schema=schema)
                    except jsonschema.ValidationError as err:
                        print("JSON schema validation error on %s: %s" % (filename, err))
                        print("Command: %s" % req.command())
                        try:
                            print("Response: %s" % res)
                        except UnicodeDecodeError as err:
                           print("Response: (unprintable)")
                        print("Schema: %s" % json.dumps(schema, indent=2))
                        exit(1)
        
    print("Done.")

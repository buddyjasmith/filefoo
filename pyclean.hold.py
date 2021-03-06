#!/usr/local/bin/python3
from __future__ import print_function, unicode_literals

# Standard library modules.
from    datetime import datetime   
import  filecmp                     
import  itertools                            
import  json
from    math import log
import  os
import  re                      
import  sys
import  time
import  threading               


# Other library modules.
from    columnar import columnar    # used to print columnar layouts
import  clr                         # https://pypi.org/project/clr/
import  humanfriendly               # https://pypi.org/project/humanfriendly/

# Local libray modules.
from borg import Borg
from spinner import Spinner
from whaaaaat import style_from_dict, Token, prompt, print_json, Separator

DEBUG = False

if sys.platform.lower() == "win32":
    os.system('color')


def dprint(foo):
    if DEBUG:
        print(foo)

class Counts(Borg):
    """ Singleton (kinda) class to keep totals. Where totals = number of files, size of found files, etc.
    """

    def __init__(self):
        Borg.__init__(self)
        self.files = 0
        self.folders = 0
        self.found = 0
        self.size = 0
        self.minutes = 0
        self.seconds = 0

    def __str__(self):
        f1 = clr.bold.yellow(self.files)
        f2 = clr.bold.yellow(self.folders)
        f3 = clr.bold.green(self.found)
        s1 = clr.bold.yellow(humanfriendly.format_size(self.size))
        t1 = clr.bold.magenta(str(self.minutes).zfill(2) + ':' + str(self.seconds).zfill(2))
        return f"Searched {f1} files in {f2} folders. Found {f3} matches. Size of found files is {s1}. Time for search was {t1}."

    def __repr__(self):
        return self.__str__()


class ThrowError(object):
    """ Amazing custom error handler class. Very robust :)
        Parameters:
        -----------
        message [string]        : error message
        error_keyword [bool]    : print "Error" before message
        bail [bool]             : exit program (fatal error)
    """

    def __init__(self, **kwargs):
        msg = kwargs.get('message', None)
        error_keyword = kwargs.get('error_keyword', True)
        bail = kwargs.get('bail', True)

        # Adds red "Error:" to output
        if error_keyword:
            msg = f"{clr.bold.red('Error:')} " + msg
        print(msg)
        if bail:
            sys.exit()


class File(object):
    """ Represents a file along with its info. Really used to print file info nicely.

        Parameters:
        -----------
        base_dir    [string]    : base directory
        name        [string]    : file name
        size        [int]       : file size
        mdate       [string]    : file modified date
        ftype       [string]    : file extension

    """

    def __init__(self, base_dir, name, size, mdate, ftype):
        self.base_dir = base_dir
        self.name = name
        self.size = size
        self.mdate = mdate
        self.ftype = ftype

    def __str__(self):
        return "[{} : {} : {} : {} : {}]".format(self.base_dir, self.name, humanfriendly.format_size(self.size), self.mdate, self.ftype)

    def __repr__(self):
        return '\n\t\tFile:' + self.__str__()


class FileCollection(object):
    """ A collection of files :) Or a reflection of a "folder" with some detailed info.
    """

    def __init__(self):
        self.base = None
        self.size = 0
        self.files = []
        self.count = 0

    def add_file(self, f):
        """ Add a file to the collection.

            Parameters:
            ---------------
            f [string] : filename
        """
        self.files.append(f)
        self.count += 1

    def __str__(self):
        b = self.base
        s = humanfriendly.format_size(self.size)
        f = self.files
        c = self.count

        return "\n\tbase: {}\n\tsize:{}\n\tcount:{}\n\tfiles:{}".format(str(b), str(s), str(c), str(f))

    def __repr__(self):
        return 'FileCollection:' + self.__str__()


class Usage(object):
    @staticmethod
    def print(classname,commands):
        command_list = []
        for command, description in commands.items():
            command_list.append([' '+clr.green(command), ' '+clr.yellow(description)])

        usage = columnar(command_list, headers=[clr.green.bold(' Command'), clr.yellow.bold(' Description')])

        return f"{classname} Usage:\n" + usage

class FindFiles(object):
    """ A helper class to find files based on various parameters.
    """
    valid_commands = {
        'binary': 'Convert byte file sizes into binary powers of 2.',
        'date': 'Date to match files to (exact match) so be careful with times.',
        'file_types': 'Allowed file types (e.g. =png,jpg,bmp ) (based on extension not file structure).',
        'min_date': 'Min date for matched files (e.g. ="2019-02-22 13:30").',
        'max_date': 'Max date for matched files.',
        'min_size': 'Min allowed file size (e.g. =1000 or =1K or =4GB etc.).',
        'max_size': 'Max allowed file size.',
        'out_filename': 'Name of file to save results of search.',
        'path': 'Start search here.',
        'print_summary': 'Print a tabular summary of files.',
        'size': 'Size file should be (with some delta because exact matches are not reliable).',
        'size_delta': 'Size delta for a size match (+/- some small value). Default = 1 percent of size.',
        'substr_match': 'String to partially match a filename.'
    }
    
    def __init__(self, **kwargs):
        self.valid_commands = FindFiles.valid_commands
        self._init_search(**kwargs)


    def _init_search(self,**kwargs):
        for k, v in kwargs.items():
            if not k in self.valid_commands:
                ThrowError(
                    message=f"{k}={v} is not a valid command parameter.", bail=False)
                ThrowError(message=self._usage(), error_keyword=False)

        self.binary = kwargs.get('binary', True)
        self.date = kwargs.get('date', None)
        self.file_types = kwargs.get('file_types', None)
        self.min_date = kwargs.get('min_date', None)
        self.max_date = kwargs.get('max_date', None)
        self.min_size = kwargs.get('min_size', None)
        self.max_size = kwargs.get('max_size', None)
        self.out_filename = kwargs.get('out_filename', None)
        self.path = kwargs.get('path', '.')
        self.size = kwargs.get('size', None)
        self.size_delta = kwargs.get('size_delta', None)
        self.substr_match = kwargs.get('substr_match', None)

        self.counts = Counts()

        # Turn path into absolute
        self.path = os.path.abspath(self.path)

        if not os.path.isdir(self.path):
            ThrowError(message=f"Path: {self.path} is not a valid directory.")

        # turn specified file types into a list
        if self.file_types != None:
            self.file_types = self._try_parsing_file_types(self.file_types)

        # If binary flag is unknown, make it false
        if self.binary == 'False':
            self.binary = False
        elif self.binary == 'True':
            self.binary = True

        # Convert sizes to bytes (if they exist)
        self.max_size = self._fix_size(self.max_size, self.binary)
        self.min_size = self._fix_size(self.min_size, self.binary)
        self.size = self._fix_size(self.size, self.binary)
        self.size_delta = self._fix_size(self.size_delta, self.binary)

        # Make sure date input is parsable format
        self.min_date = self._try_parsing_date(self.min_date)
        self.max_date = self._try_parsing_date(self.max_date)
        self.date = self._try_parsing_date(self.date)

        # container of results
        self.results = {}

    def _reset_search(self,**kwargs):
        pass

    def find(self):
        """ Public find function that calls a "spinner" to show it's working and then print a summary of items found.

            Params:
            -------------
            none
        """

        with Spinner(self.counts):
            self._find(self.path)

        sys.stdout.write("\r")
        sys.stdout.write(" "*200) # needs to be robust hard coded right now to erase line
        sys.stdout.write("\r\n")


        return self.results

    def get_result_directories(self):
        """ Return a list of directories in which files were found.
        """

        dir_list = []

        for dirname, directory in self.results.items():
            if directory.size > 0:
                dir_list.append(directory)

        return dir_list

    def get_result_files(self, dirnames=[]):
        """ Return a list of files in one or all of the directories.
        """
        file_list = []

        if len(dirnames) == 0:
            for dname, directory in self.results.items():
                for f in directory.files:
                    file_list.append(f)
        else:
            for dirname in dirnames:
                if dirname in self.results:
                    for f in self.results[dirname].files:
                        file_list.append(f)
                else:
                    ThrowError(
                        f"Directory name {dirname} not in 'dirtree'.", bail=False)

        return file_list

    def print_tabular_result(self, file_name=None):
        """ Prints a tabular output of the found files.
        """
        files_list = []
        count = 1
        for d, dd in self.results.items():
            if dd.size > 0:
                for f in dd.files:
                    files_list.append(
                        [count, f.base_dir, f.name, humanfriendly.format_size(f.size), f.mdate, f.ftype])
                    count += 1

        table = columnar(files_list, headers=[
                         '#', 'Path', 'Name', 'Size', 'Date', 'Ext'])
        if file_name == None:
            print(table)
        else:
            with open(file_name, "w") as f:
                f.write(table)

    def save_json(self, out_filename=None):
        """ Saves the list of found files to a json file.
        """

        if out_filename == None:
            out_filename = self.out_filename

        files_list = []
        count = 1
        for d, dd in self.results.items():
            if dd.size > 0:
                for f in dd.files:
                    files_list.append({
                        'id': count,
                        'path': f.base_dir,
                        'name': f.name,
                        'size': f.size,
                        'modify_date': f.mdate,
                        'ext': f.ftype
                    })
                    count += 1

        with open(out_filename, "w") as f:
            f.write(json.dumps(files_list))

        return files_list

    def _find(self, path=None):
        """ Returns all the files in a given path based on search criteria.

            Params:
            -----------
            path [string]   : path to search
        """
        global FILES
        global FOLDERS
        global FOUND

        if path == None:
            path = self.path
        else:
            # Turn path into absolute
            path = os.path.abspath(path)

        # Traverse directory to find files
        for (dirpath, dirnames, filenames) in os.walk(path):
            dprint(dirnames)
            self.results[dirpath] = FileCollection()
            for d in dirnames:
                dpath = os.path.join(dirpath, d)
                if not dpath in self.results:
                    self.counts.folders += 1
                    self.results[dpath] = FileCollection()

            sum = 0
            for f in filenames:
                self.counts.files += 1
                self.results[dirpath].base = dirpath
                fpath = os.path.join(dirpath, f)

                # check to see if we should keep the file
                keeps = self._keep_file(fpath)
                print(keeps)
                if keeps != False:
                    self.counts.found += 1
                    fs, fd, fe = keeps
                    self.counts.size += fs
                    sum += fs
                    dprint((fs, f, fd, fe))
                    self.results[dirpath].add_file(
                        File(dirpath, f, fs, fd, fe))

            self.results[dirpath].size = sum

        return self.results

    def _keep_file(self, fpath):
        """ Filter with all params to determine if we keep file in our search.

            Params:
            -------------
            fpath [string] : path to file

            Returns:
            -------------
            tuple with (file_size, file_date, file_extension)
        """
        if not os.path.isfile(fpath):
            return False

        file_size = os.path.getsize(fpath)
        filename, file_extension = os.path.splitext(fpath)
        file_date = datetime.fromtimestamp(
            os.path.getmtime(fpath)).strftime('%Y-%m-%d %H:%S')

        if self._size_check(file_size) == False:
            return False

        if self._date_check(fpath) == False:
            return False

        if self._types_check(file_extension) == False:
            return False

        if self._substr_check(filename) == False:
            return False

        #dprint("returning: {} {} {} ".format(file_size, file_date, file_extension))
        return (file_size, file_date, file_extension)

    def _substr_check(self, filename, case_sensitive=False):
        """ Checks to see if some substring is contianed in the filename.
        """
        if self.substr_match == None:
            return True

        if not case_sensitive:
            if not self.substr_match.lower() in filename.lower():
                return False
        else:
            if not self.substr_match in filename:
                return False
        return True

    def _size_check(self, file_size):
        """ Checks a files size to make sure:
            1) it equals some "size" +/- some delta
            2) it is in between some min/max size
        """
        if self.size != None:
            if self.size_delta == None:
                raise Exception(
                    'Searching for size requires a "size_delta" as well .....')

            if file_size < (self.size - self.size_delta) or (self.size + self.size_delta) < file_size:
                dprint("failed size: {} <> {} <> {}".format(humanfriendly.format_size(
                    self.size - self.size_delta), file_size, humanfriendly.format_size(self.size + self.size_delta)))
                return False

        if self.min_size != None or self.max_size != None:
            if self.min_size != None:
                if file_size < self.min_size:
                    dprint("failed min_size: {}<{}".format(
                        file_size, self.min_size))
                    return False

            if self.max_size != None:
                if file_size > self.max_size:
                    dprint("failed max_size: {}<{}".format(
                        file_size, self.max_size))
                    return False
        return True

    def _types_check(self, file_extension):
        """ Checks to make sure file has proper extension. Doesn't look at file structure
        """
        if self.file_types != None:
            if not file_extension in self.file_types:
                dprint("failed file_extension: {}<{}".format(
                    file_extension, self.file_types))
                return False
        return True

    def _date_check(self, fpath):
        """ Checks a files modified date is equal to or within a min and max date.
        """
        if self.date != None:
            search_date = datetime.fromtimestamp(
                self.date).strftime('%Y-%m-%d')
            file_date = datetime.fromtimestamp(
                os.path.getmtime(fpath)).strftime('%Y-%m-%d')

            if search_date != file_date:
                dprint("failed date: {}!={}".format(file_date, search_date))
                return False
        elif self.min_date != None or self.max_date != None:
            file_date = os.path.getmtime(fpath)

            #dprint("file_date: {}".format(file_date))

            if self.min_date != None:
                #dprint("min_date: {}".format(self.min_date))
                if file_date < self.min_date:
                    #dprint("failed min_date: {}<{}".format(str_file_date, str_min_date))
                    return False

            if self.max_date != None:
                #dprint("max_date: {}".format(self.max_date))
                if file_date >= self.max_date:
                    #dprint("failed max_date: {}>{}".format(file_date, str_max_date))
                    return False
        return True

    def _try_parsing_date(self, string_date):
        """ Try's to turn a string date into a python formatted date type.

            Params:
            ----------
            string_date [string] : datetime formatting string

            Returns:
            ----------
            datetime
        """
        if string_date == None:
            return None

        string_date = re.sub("\.|/|-|,|:", " ", string_date)

        for fmt in ('%m %d %Y', '%m %d %y', '%m %d %Y %H %M', '%m %d %y %H %M',
                    '%d %m %Y', '%d %m %y', '%d %m %Y %H %M', '%d %m %y %H %M',
                    '%Y %m %d', '%y %m %d', '%Y %m %d %H %M', '%y %m %d %H %M'
                    ):
            try:
                t = time.mktime(datetime.strptime(
                    string_date, fmt).timetuple())
                return t
            except ValueError:
                dprint(string_date)
        ThrowError(message='no valid date format found')

    def _try_parsing_file_types(self, file_types):
        """ Takes a filetypes string (one or more extensions) and turns them into
                a list of acceptable extensions.

            Params:
            ----------
            file_types [string] : one or more file types (e.g. 'py' or 'dat,py,exe' or 'py cpp hpp' etc.)

            Returns:
            ----------
            list of file types: e.g. ['py', 'cpp', 'hpp']
        """
        file_types = file_types.strip()

        if len(file_types) < 5:
            return ['.'+file_types]

        for delimiter in (' ', ',', ':'):
            if delimiter in file_types:

                return ['.'+x for x in file_types.split(delimiter)]

        raise Exception("Delimiter not found!")

    def _fix_size(self, size, binary=False):
        """ Turns a human readable filesize into bytes, or leaves it None

            Params:
            ---------
            size [string] : string size (e.g 100M or 32k )
            binary [bool] : boolean True means we want binary sizes (e.g. 1k = 1024 instead of 1000)

            Returns:
            ---------
            bytes [integer] or None
        """
        if size == None:
            return None
        else:
            return humanfriendly.parse_size(size, binary=binary)

class CompareFiles(object):
    """
    https://pymotw.com/2/filecmp/
    """

    valid_commands = {
        'path': 'Start search here.',
        'deep': 'Do a deep compare',
        'type': 'Files or directories.',
    }

    def __init__(self,**kwargs):

        self.valid_commands = CompareFiles.valid_commads
        self._init(**kwargs)

    def _init(self,**kwargs):
        for k, v in kwargs.items():
            if not k in self.valid_commands:
                ThrowError(
                    message=f"{k}={v} is not a valid command parameter.", bail=False)
                ThrowError(message=self._usage(), error_keyword=False)

        self.path = kwargs.get('path', None)
        self.deep = kwargs.get('deep', False)
        self.type = kwargs.get('type', 'Files')

    def file_compare(self,path = None):
        if path == None:
            path = self.path

        # Still no path ?!?
        if path == None:
            ThrowError(message=self._usage(), error_keyword=False)

        files = os.listdir(self.path)

        for f1, f2 in itertools.combinations(files, 2):
            if filecmp.cmp(f1, f2):
                print(f1, f2)

    def directory_compare(self):
        c = filecmp.dircmp(filepath1, filepath2)
        _report_recursive(c)

    def _report_recursive(self,dcmp):
        for name in dcmp.diff_files:
            print("DIFF file %s found in %s and %s" % (name, 
                dcmp.left, dcmp.right))
        for name in dcmp.left_only:
            print("ONLY LEFT file %s found in %s" % (name, dcmp.left))
        for name in dcmp.right_only:
            print("ONLY RIGHT file %s found in %s" % (name, dcmp.right))
        for sub_dcmp in dcmp.subdirs.values():
            print_diff_files(sub_dcmp)

class Summary(object):
    pass

# TEMPORARY
class Interactive(FindFiles):
    def __init__(self,**kwargs):
        super().__init__(**kwargs)

        self.find()
        self.what_now()
        self.save_results()

    def what_now(self):
        print(self.counts)

        style = style_from_dict({
            Token.Separator: '#6C6C6C',
            Token.QuestionMark: '#FF9D00 bold',
            #Token.Selected: '',  # default
            Token.Selected: '#5F819D',
            Token.Pointer: '#FF9D00 bold',
            Token.Instruction: '',  # default
            Token.Answer: '#5F819D bold',
            Token.Question: '',
        })


        questions = [
            {
                'type': 'confirm',
                'message': f"Save results to: {self.out_filename}: ",
                'name': 'save',
                'default': 'True'
            }
        ]
    
    def save_results(self):
        style = style_from_dict({
            Token.Separator: '#6C6C6C',
            Token.QuestionMark: '#FF9D00 bold',
            #Token.Selected: '',  # default
            Token.Selected: '#5F819D',
            Token.Pointer: '#FF9D00 bold',
            Token.Instruction: '',  # default
            Token.Answer: '#5F819D bold',
            Token.Question: '',
        })

        if self.out_filename != None:

            questions = [
                {
                    'type': 'confirm',
                    'message': f"Save results to: {self.out_filename}: ",
                    'name': 'save',
                    'default': 'True'
                }
            ]
        else: # NOT DONE

            questions = [
                {
                    'type': 'expand',
                    'message': 'Save file on `file.js`: ',
                    'name': 'overwrite',
                    'default': 'a',
                    'choices': [
                        {
                            'key': 'y',
                            'name': 'Overwrite',
                            'value': 'overwrite'
                        },
                        {
                            'key': 'a',
                            'name': 'Overwrite this one and all next',
                            'value': 'overwrite_all'
                        },
                        {
                            'key': 'd',
                            'name': 'Show diff',
                            'value': 'diff'
                        },
                        Separator(),
                        {
                            'key': 'x',
                            'name': 'Abort',
                            'value': 'abort'
                        }
                    ]
                }
            ]

        answer = prompt(questions, style=style)
        if answer['save']:
            self.save_json()

    def move_file(self,src, dest):
        """ Move a given file from `src` to `dst`

            Params:
            ---------
            src [string]  : path to source file
            dest [string] : path to new location

            Returns:
            ---------
            bool success
        """
        pass


    def delete_file(self,src, ask=True):
        """ Delete a file from disk

            Params:
            ----------
            src [string]  : path to file
            ask [bool] : True = prompt user before deleting

            Returns:
            -----------
            bool success
        """
        pass


def mykwargs(sysargs):
    """ Creates a dictionary of key=value pairs.
        If an argument of format 'k=v' with no spaces is present, it is added 
        to `kwargs dictionary`, otherwise it is added to the `args list`.

        Parameters:
        -----------
        sysargs [list] : list of arguments (usually sys.argv)

        Returns:
        --------
        tuple(dict,list) : kwargs dict and args list
    """
    args = []
    kwargs = {}

    for a in sysargs:
        if '=' in a:
            k, v = a.split('=')
            kwargs[k] = v
        else:
            args.append(a)

    return kwargs, args


def main(*args,**kwargs):

    valid_commands = {
        'fin': "Find files or directories.",
        'com': "Compare files or directories.",
        'sum': "Summarize files or directories.",
        'mov': "Move files or directories.",
        'del': "Delete files or directories."
    }

    if len(args) < 2:
        print("Missing one of the following from your command: ")
        print(Usage.print('main',valid_commands))
        return
    elif not args[1] in valid_commands:
        print("Command not known: ")
        print(Usage.print('main',valid_commands))
    else:
        if args[1] == 'fin':
            f = FindFiles(**kwargs)
            result = f.find()
            print(result)
            print(f.counts)

        elif args[1] == 'com':
            CompareFiles(**kwargs)


if __name__ == '__main__':

    kwargs, args = mykwargs(sys.argv)

    f = main(*args,**kwargs)

 

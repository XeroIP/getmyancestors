# coding: utf-8

# global imports
from __future__ import print_function
import re
import sys
import time
from urllib.parse import unquote
import getpass
import asyncio
import argparse

# local imports
from getmyancestors.classes.tree import Tree
from getmyancestors.classes.session import Session
from getmyancestors.classes.narrative import print_narrative


def render_progress(desc, done, total):
    """Draw an in-place progress bar on stderr.

    No-op when stderr is not a terminal (so redirected logs stay clean) or
    when there is nothing to do. Caller is responsible for skipping this in
    verbose mode, where the per-request trace already shows progress.
    """
    if total <= 0 or not sys.stderr.isatty():
        return
    bar_len = 30
    filled = int(bar_len * done / total)
    bar = "#" * filled + "-" * (bar_len - filled)
    sys.stderr.write(
        "\r%s [%s] %d/%d (%d%%)" % (desc, bar, done, total, done * 100 // total)
    )
    sys.stderr.flush()
    if done == total:
        sys.stderr.write("\n")



def main():
    parser = argparse.ArgumentParser(
        description="Retrieve GEDCOM data from FamilySearch Tree (4 Jul 2016)",
        add_help=False,
        usage="getmyancestors -u username -p password [options]",
    )
    parser.add_argument(
        "-u", "--username", metavar="<STR>", type=str, help="FamilySearch username"
    )
    parser.add_argument(
        "-p", "--password", metavar="<STR>", type=str, help="FamilySearch password"
    )
    parser.add_argument(
        "-i",
        "--individuals",
        metavar="<STR>",
        nargs="+",
        type=str,
        help="List of individual FamilySearch IDs for whom to retrieve ancestors",
    )
    parser.add_argument(
        "-a",
        "--ascend",
        metavar="<INT>",
        type=int,
        default=4,
        help="Number of generations to ascend [4]",
    )
    parser.add_argument(
        "-d",
        "--descend",
        metavar="<INT>",
        type=int,
        default=0,
        help="Number of generations to descend [0]",
    )
    parser.add_argument(
        "-m",
        "--marriage",
        action="store_true",
        default=False,
        help="Add spouses and couples information [False]",
    )
    parser.add_argument(
        "-r",
        "--get-contributors",
        action="store_true",
        default=False,
        help="Add list of contributors in notes [False]",
    )
    parser.add_argument(
        "-c",
        "--get_ordinances",
        action="store_true",
        default=False,
        help="Add LDS ordinances (need LDS account) [False]",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Increase output verbosity [False]",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        metavar="<INT>",
        type=int,
        default=60,
        help="Timeout in seconds [60]",
    )
    parser.add_argument(
        "--rate-limit",
        metavar="<INT>",
        type=int,
        help="Max # requests per second",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["gedcom", "markdown"],
        default="gedcom",
        help="Output format: gedcom (5.5.1) or markdown narrative [gedcom]",
    )
    parser.add_argument(
        "--show-password",
        action="store_true",
        default=False,
        help="Show password in .settings file [False]",
    )
    parser.add_argument(
        "--save-settings",
        action="store_true",
        default=False,
        help="Save settings into file [False]",
    )
    parser.add_argument(
        "-o",
        "--outfile",
        metavar="<FILE>",
        type=argparse.FileType("w", encoding="UTF-8"),
        default=sys.stdout,
        help="output GEDCOM file [stdout]",
    )
    parser.add_argument(
        "-l",
        "--logfile",
        metavar="<FILE>",
        type=argparse.FileType("w", encoding="UTF-8"),
        default=False,
        help="output log file [stderr]",
    )
    parser.add_argument(
        "--client_id", metavar="<STR>", type=str, help="Use Specific Client ID"
    )
    parser.add_argument(
        "--redirect_uri", metavar="<STR>", type=str, help="Use Specific Redirect Uri"
    )

    # extract arguments from the command line
    try:
        parser.error = parser.exit
        args = parser.parse_args()
    except SystemExit:
        parser.print_help(file=sys.stderr)
        sys.exit(2)
    if args.individuals:
        for fid in args.individuals:
            if not re.match(r"[A-Z0-9]{4}-[A-Z0-9]{3}", fid):
                sys.exit("Invalid FamilySearch ID: " + fid)

    args.username = (
        args.username if args.username else input("Enter FamilySearch username: ")
    )
    args.password = (
        args.password
        if args.password
        else getpass.getpass("Enter FamilySearch password: ")
    )

    time_count = time.time()

    # Report settings used when getmyancestors is executed
    if args.save_settings and args.outfile.name != "<stdout>":

        def parse_action(act):
            if not args.show_password and act.dest == "password":
                return "******"
            value = getattr(args, act.dest)
            return str(getattr(value, "name", value))

        formatting = "{:74}{:\t>1}\n"
        settings_name = args.outfile.name.split(".")[0] + ".settings"
        try:
            with open(settings_name, "w") as settings_file:
                settings_file.write(
                    formatting.format("time stamp: ", time.strftime("%X %x %Z"))
                )
                for action in parser._actions:
                    settings_file.write(
                        formatting.format(
                            action.option_strings[-1], parse_action(action)
                        )
                    )
        except OSError as exc:
            print(
                "Unable to write %s: %s" % (settings_name, repr(exc)), file=sys.stderr
            )

    # initialize a FamilySearch session and a family tree object
    print("Login to FamilySearch...", file=sys.stderr)
    fs = Session(
        args.username,
        args.password,
        args.client_id,
        args.redirect_uri,
        args.verbose,
        args.logfile,
        args.timeout,
        args.rate_limit,
    )
    if not fs.logged:
        sys.exit(2)
    _ = fs._
    tree = Tree(fs)

    # check LDS account
    if args.get_ordinances:
        test = fs.get_url(
            "/service/tree/tree-data/reservations/person/%s/ordinances" % fs.fid, {}, no_api=True
        )
        if not test or test["status"] != "OK":
            print("Need an LDS account")
            sys.exit(2)

    try:
        # add list of starting individuals to the family tree
        todo = args.individuals if args.individuals else [fs.fid]
        print(_("Downloading starting individuals..."), file=sys.stderr)
        tree.add_indis(todo)

        # download ancestors
        todo = set(tree.indi.keys())
        done = set()
        for i in range(args.ascend):
            if not todo:
                break
            done |= todo
            print(
                _("Downloading generation %s of ancestors...") % (i + 1),
                file=sys.stderr,
            )
            todo = tree.add_parents(todo) - done

        # download descendants
        todo = set(tree.indi.keys())
        done = set()
        for i in range(args.descend):
            if not todo:
                break
            done |= todo
            print(
                _("Downloading generation %s of descendants...") % (i + 1),
                file=sys.stderr,
            )
            todo = tree.add_children(todo) - done

        # download spouses
        if args.marriage:
            print(_("Downloading spouses and marriage information..."), file=sys.stderr)
            todo = set(tree.indi.keys())
            tree.add_spouses(todo)

        # download ordinances, notes and contributors
        async def download_stuff(loop):
            futures = set()
            for fid, indi in tree.indi.items():
                futures.add(loop.run_in_executor(None, indi.get_notes))
                futures.add(loop.run_in_executor(None, indi.get_memories))
                if args.get_ordinances:
                    futures.add(loop.run_in_executor(None, tree.add_ordinances, fid))
                if args.get_contributors:
                    futures.add(loop.run_in_executor(None, indi.get_contributors))
            for fam in tree.fam.values():
                futures.add(loop.run_in_executor(None, fam.get_notes))
                if args.get_contributors:
                    futures.add(loop.run_in_executor(None, fam.get_contributors))
            total = len(futures)
            done = 0
            for future in asyncio.as_completed(futures):
                await future
                done += 1
                if not args.verbose:
                    render_progress(_("Downloading notes & memories"), done, total)

        loop = asyncio.get_event_loop()
        print(
            _("Downloading notes")
            + (
                (("," if args.get_contributors else _(" and")) + _(" ordinances"))
                if args.get_ordinances
                else ""
            )
            + (_(" and contributors") if args.get_contributors else "")
            + "...",
            file=sys.stderr,
        )
        loop.run_until_complete(download_stuff(loop))

    finally:
        # compute number for family relationships and print output
        tree.reset_num()
        if args.format == "markdown":
            print_narrative(tree, args.outfile)
        else:
            tree.print(args.outfile)
        print(
            _(
                "Downloaded %s individuals, %s families, %s sources and %s notes "
                "in %s seconds with %s HTTP requests."
            )
            % (
                str(len(tree.indi)),
                str(len(tree.fam)),
                str(len(tree.sources)),
                str(len(tree.notes)),
                str(round(time.time() - time_count)),
                str(fs.counter),
            ),
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()

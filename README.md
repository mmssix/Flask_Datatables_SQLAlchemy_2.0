### Purpose:
To test the update to [sqlalchemy-datatables](https://github.com/orf/datatables/tree/master) from sqlalchmy 1.4, to 2.0.

Run with: `https://github.com/orf/datatables/tree/master`

Open shell with: `https://github.com/orf/datatables/tree/master`

This example site should then be running at : http://127.0.0.1:5000/


### The Issue:
Im sure there may be more issues, but right now the deprecation 
of [the join aliased](https://docs.sqlalchemy.org/en/14/changelog/migration_20.html#orm-query-join-aliased-true-from-joinpoint-removed)
is whats breaking.  There may also be an issue with automatic serialization of lazy joined tables as well.


### Outcome
The "datatables.py" file here is the code that works under 1.4.  Please make any 
changes necessary to get it working under 2.0.  The single page flask app should give you a starting point to 
test against.
import net from 'node:net';
// The import probe: with the network constructors patched in the parent
// helper, this module import must throw 'network denied'. It exercises a
// real socket connect attempt, so a silent online environment fails the
// probe guard ("Import guard missing") instead of passing.
net.connect(9,'127.0.0.1');

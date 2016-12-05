# Download reference data from http://ctg.cncr.nl/software/magma (for example g1000_eur)
# Then you can run the tool as follows:
#    python make_ld_matrix.py --ref 2558411_ref.bim --bfile g1000_eur --ld_window_r2 0.1 --savemat ldmat_p1.mat
#
# Another example is for situation where you've already generated LD matrix by plink:
#    python make_ld_matrix.py --ref 2558411_ref.bim --ldfile tmp.ld --savemat ldmat.mat

from subprocess import call, check_output
import subprocess
import pandas as pd
import numpy as np
import argparse
import sys

def execute_command(command):
    print("Execute command: {}".format(command))
    process = subprocess.Popen(command.split(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(process.communicate()[0].decode("utf-8"))
    #print(subprocess.check_output(command.split()).decode("utf-8"))


def parse_args(args):
    parser = argparse.ArgumentParser(description="Generate LD matrix from genotype matrix")
    parser.add_argument("--ref", type=str, help="Reference file (for example 2558411_ref.bim or 9279485_ref.bim.")
    parser.add_argument("--bfile", type=str, help="Genotypes in plink binary format")
    parser.add_argument("--ldfile", type=str, default=None, help="Path to .ld file generated by plink (takes priority over bfile, ld_window_kb and ld_window_r2")
    parser.add_argument("--ld_window_kb", default=5000, type=int, help="Window in KB")
    parser.add_argument("--ld_window_r2", default=0.1, type=float, help="LD r2 threshold")
    parser.add_argument("--chunksize", default=100000, type=int, help="Chunk size when reading ld matrix")
    parser.add_argument("--plink", default="plink", type=str, help="location of plink executable")
    parser.add_argument("--savemat", default=None, type=str, help="Generate matfile for Matlab.")
    parser.add_argument("--saveltm", default=None, type=str, help="Generate 'ltm' --- lower triangular matrix in plain text format.")
    return parser.parse_args(args)

def make_ld_matrix(args):
    if not args.savemat and not args.saveltm:
        raise ValueError('No output requested, use --savemat or --saveltm')

    # Read the template
    print('Reading {0}...'.format(args.ref))
    ref = pd.read_csv(args.ref, delim_whitespace=True)
    nsnp = ref.shape[0]
    chrpos_to_id = dict([((chr, pos), index) for chr, pos, index in zip(ref['CHR'], ref['BP'], ref.index)])
    if len(chrpos_to_id) != nsnp: raise ValueError("Duplicated CHR:POS pairs found in the reference file")

    if args.ldfile is None:
        # Create LD file in table format
        execute_command('{0} --bfile {1} --r2 gz --ld-window-kb {2} --ld-window 999999 --ld-window-r2 {3} --out tmp'.format(args.plink, args.bfile, args.ld_window_kb, args.ld_window_r2))
        args.ldfile = 'tmp.ld.gz'

    # Read resulting LD matrix
    reader = pd.read_csv(args.ldfile, delim_whitespace=True, chunksize=args.chunksize)

    print('Parsing {0}...'.format(args.ldfile))
    total_df = None
    for i, df in enumerate(reader):
        id1tmp = [chrpos_to_id.get((chr, pos), None) for chr, pos in zip(df['CHR_A'], df['BP_A'])]
        id2tmp = [chrpos_to_id.get((chr, pos), None) for chr, pos in zip(df['CHR_B'], df['BP_B'])]
        mask = [(i1 is not None and i2 is not None) for i1, i2 in zip(id1tmp, id2tmp)]
        id1 = [value for index, value in enumerate(id1tmp) if mask[index] == True]
        id2 = [value for index, value in enumerate(id2tmp) if mask[index] == True]
        val = [value for index, value in enumerate(df['R2']) if mask[index] == True]
        df_tmp = pd.DataFrame(data={'id1': id1, 'id2': id2, 'val': val})
        total_df = df_tmp if total_df is None else total_df.append(df_tmp, ignore_index=True)
        print('\rFinish {0} entries ({1} after joining with ref)'.format(i * args.chunksize + len(mask), total_df.shape[0]), end='')
    print('. Done.')

    print('Detecting duplicated entries...')
    old_size = total_df.shape[0]
    total_df.drop_duplicates(subset=['id1', 'id2'], keep='first', inplace=True)
    print('Drop {} duplicated entries'.format(old_size-total_df.shape[0]))

    # Output the result as lower diagonal matrix
    if args.saveltm:
        print('Save result as lower diagonal matrix to {0}...'.format(args.saveltm))
        from scipy.sparse import csr_matrix
        id1=list(total_df['id1']); id2 = list(total_df['id2']); val = list(total_df['val'])
        assert(all([(i < j) for (i, j) in zip(id1, id2)]))  # expect that plink output lower diagonal matrix
        csr = csr_matrix((val, (id2, id1)), shape=(nsnp, nsnp))

        with open(args.saveltm, 'w') as result:
            result.write('1.0\n')
            for i in range(1, nsnp):
                values =  csr[i, :].todense()[0, 0:i].A1
                values_str = '\t'.join(str(x) for x in values)
                result.write('{0}\t1.0\n'.format(values_str))
    
    # Output the result in matlab format
    if args.savemat:
        print('Save result in matlab format to {0}...'.format(args.savemat))
        import scipy.io as sio
        sio.savemat(
            args.savemat, {'id1':[i + 1 for i in total_df['id1']], 'id2':[i + 1 for i in total_df['id2']], 'val':list(total_df['val']), 'nsnp':nsnp},
            format='5', do_compression=False, oned_as='column')

        print("""
The results are saved into {0}. Now you should open matlab and execute the following commands to re-save the result as matlab sparse matrix:
    load {0}
    LDmat = sparse(double(id1),double(id2),true,double(nsnp),double(nsnp));
    LDmat = LDmat | speye(double(nsnp));
    LDmat = LDmat | (LDmat - LDmat');
    save('LDmat.mat', 'LDmat', '-v7.3')
""".format(args.savemat))


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    make_ld_matrix(args)
    print("Done.")

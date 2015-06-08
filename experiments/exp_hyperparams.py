import bayeslite.crosscat
import bayeslite.core as core
import exputils as eu

import numpy as np
import pandas as pd


from crosscat.MultiprocessingEngine import MultiprocessingEngine
from crosscat.tests.quality_tests import synthetic_data_generator as sdg
from bayeslite.shell.pretty import pp_cursor
from bayeslite.sqlite3_util import sqlite3_quote_name

import sys
import tempfile
import json

DO_PLOT = True
try:
    from matplotlib import pyplot as plt
    from matplotlib import gridspec
    try:
        import seaborn as sns
    except:
        pass
except ImportError:
    DO_PLOT = False


def pprint(cursor):
    return pp_cursor(sys.stdout, cursor)

def train_models(args):

    bdb = bayeslite.bayesdb_open()
    engine = bayeslite.crosscat.CrosscatMetamodel(
            MultiprocessingEngine())
    bayeslite.bayesdb_register_metamodel(bdb, engine)

    
    colno = args['colno']
    coltypes = args['coltypes']

    model_hypers = {i:[] for i in xrange(args['n_model'])}
    for k in xrange(args['n_model']):
        
        print "ANALYZING MODEL {}: Iterations".format(k),
        sys.stdout.flush()

        temp = tempfile.NamedTemporaryFile()
        eu.data_to_csv(np.asarray(args['dataset']), temp.name)
        
        btable = 'hyper{}_{}'.format(args['n_model'], k)
        generator = 'hyper{}_cc{}'.format(args['n_model'], k)
        bayeslite.bayesdb_read_csv_file(bdb, btable, temp.name, header=True, create=True)
        qt_btable = sqlite3_quote_name(btable)
        temp.close()

        # bql = '''
        # SELECT * FROM {}
        # '''.format(qt_btable)
        # pprint(bdb.execute(bql))

        C = ['c{} {}'.format(s, coltypes[s]) for s in xrange(len(coltypes))]
        bql = '''
        CREATE GENERATOR {} FOR {}
            USING crosscat (
                {}
            );
        '''.format(generator, qt_btable, str(C)[2:-2].replace('\'',''))
        print bql
        bdb.execute(bql)

        bql = '''
        INITIALIZE 1 MODELS FOR {}
        '''.format(generator)
        bdb.execute(bql)

        total_iters = args['step_size']
        while (total_iters <= args['target_iters']):
            print total_iters
            sys.stdout.flush()

            bql = '''
            SELECT * FROM {};
            '''.format(sqlite3_quote_name('bayesdb_crosscat_diagnostics'))
            pprint(bdb.execute(bql))
        
            bql = '''
            ANALYZE {} FOR {} ITERATIONS WAIT;
            '''.format(generator, args['step_size'])
            bdb.execute(bql)

            generator_id = core.bayesdb_get_generator(bdb, generator)
            sql = '''
            SELECT theta_json FROM bayesdb_crosscat_theta WHERE generator_id = {}
            '''.format(generator_id)
            cursor = bdb.sql_execute(sql)
            (theta_json,) = cursor.fetchall()[0]
            theta = json.loads(theta_json)
            
            model_hypers[k].append(theta['X_L']['column_hypers'][colno])

            total_iters += args['step_size']
        print

    bdb.close()
    return model_hypers

def runner(args):     
    np.random.seed(args['seed'])
    
    results = {}
    results['args'] = args
    results['hypers'] = train_models(args)

    return results

def plot(result, filename=None):

    args = result['args']
    n_model = args['n_model']
    step_size = args['step_size']
    target_iters = args['target_iters']

    fig, ax = plt.subplots()
    ax.set_xlabel('Number of Iterations')
    ax.set_ylabel(r'Hyperparamter $\mu$ (Mean of Gaussian Mixture)')
    ax.set_title('Mean of Posterior Mean with {} Samples'.format(args['n_samples']))

    xs = np.arange(step_size, target_iters + 1, step_size)
    averages = [0]*len(xs)
    for model in xrange(args['n_model']):
        (m,s,r,nu) = ([],[],[],[])
        for (i,h) in enumerate(result['hypers'][model]):
            m.append(h['mu'])
            s.append(h['shell'])
            r.append(h['r'])
            nu.append(h['nu'])
            averages[i] += h['mu'] / args['n_model']
        ax.plot(xs, m, alpha = 0.4)
    ax.plot(xs, averages, alpha = 1, color = 'black', linestyle = '--', label = 'CC Mean')
    ax.text(ax.get_xlim()[1], averages[-1], r'$\mu_{{CC}} = {:.3f}$'.format(averages[-1]), color = 'black')

    actual_average = 0
    for i,(z,w) in enumerate(zip(args['actual_component_params'],args['actual_component_weights'])):
        ax.axhline(y = z['mu'], color = 'blue', alpha = 0.4)
        ax.text(ax.get_xlim()[1], z['mu'], r'$(w_{},\mu_{})=({:.2f},{:.2f})$'.format(i,i,w,z['mu']), color = 'blue')
        actual_average += z['mu'] * w
    ax.axhline(y = actual_average, color = 'red', linestyle='--')
    ax.text(ax.get_xlim()[1], actual_average, r'$\sum w_kp_k={:.3f}$'.format(actual_average), color = 'red')

    if not DO_PLOT:
        import time
        filename = 'exp_hyperparams_results_' + str(time.time()) + '.png'

    if filename is None:
        plt.show(block = False )
    else:
        plt.savefig(filename)

if __name__ == '__main__':
    args = {
    'n_model' : 10,
    'step_size' : 5,
    'target_iters' : 200,
    'seed' : 448
    }

    # GENERATE SYNTHETIC DATA
    cctypes = ['continu ous','continuous','multinomial', 'continuous', 'multinomial','multinomial',
    'continuous','continuous','multinomial', 'continuous', 'continuous','continuous']
    distargs = [None, None, dict(K=9), None, dict(K=7), dict(K=4),
    None, None, dict(K=9), None, None, None]
    cols_to_views = [0, 0, 0, 1, 1, 2, 1, 0, 2, 3, 1, 0]
    cluster_weights = [[.3, .3, .4],[.6, .2, .1, .1],[.4, .4, .2],[.8, .2]]
    separation = [0.6, 0.4, 0.5, 0.6]
    sdata = sdg.gen_data(cctypes, 
        1000,
        cols_to_views, 
        cluster_weights, 
        separation, 
        seed=args['seed'], distargs=distargs, 
        return_structure=True)

    coltypes = ['NUMERICAL' if s == 'continuous' else 'CATEGORICAL' for s in cctypes]
    args['coltypes'] = coltypes    
    args['colno'] = 6
    
    args['actual_component_params'] = sdata[2]['component_params'][args['colno']]
    args['actual_component_weights'] = cluster_weights[cols_to_views[args['colno']]]

    for samples in [10, 20, 50, 70, 100, 150, 200, 250, 300, 500]
        args['n_samples'] = samples
        args['dataset'] = np.asarray(sdata[0][:samples])
        result = runner(args)
        plot(result)
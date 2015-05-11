"""
@Author: Rui Shu
@Date: 4/11/15

Master -- handles the Optimizer object (which takes prior data,
interpolates based on a neural network-linear regression model, and selects the
next set of points to query). Tells worker nodes which points to query.
"""

from mpi_definitions import *
import time 

plot_it = False

def contains_row(x, X):
    """ Checks if the row x is contained in matrix X
    """
    for i in range(X.shape[0]):
        if all(X[i,:] == x):
            return True

    return False

def master_process():
    f = open("data/mpi_time_data.csv", "a")
    from learning_objective.hidden_function import evaluate, true_evaluate, get_settings
    import random
    import matplotlib.pyplot as plt
    import utilities.optimizer as op

    print "MASTER: starting with %d workers" % (size - 1)

    # Setup
    t1 = time.time()            # Get amount of time taken
    num_workers = size - 1      # Get number of workers
    closed_workers = 0          # Get number of workers EXIT'ed

    # Get settings relevant to the hidden function being used
    lim_domain, init_size, additional_query_size, init_query, domain, selection_size = get_settings()
    

    # init_query = np.random.uniform(-1, 1, size=(init_size, lim_domain.shape[1]))

    # # WARNING. SET THE THING YOURSELF FOR NOW.
    # r = np.linspace(-1, 1, 50)
    # X = np.meshgrid(r, r)
    # xx = np.atleast_2d([x.ravel() for x in X]).T
    # domain = np.atleast_2d(xx[0])
    # for i in range(1, xx.shape[0]):
    #     domain = np.concatenate((domain, np.atleast_2d(xx[i])), axis=0)

    # Acquire an initial data set
    dataset = None
    init_assigned = 0           # init query counters
    init_done = 0

    while init_done < init_size:
        # Get a worker (trainer does not initiate conversation with master)
        data = comm.recv(source=MPI.ANY_SOURCE, tag=MPI.ANY_TAG, status=status)
        source = status.Get_source()
        tag = status.Get_tag()

        if tag == WORKER_READY:
            if init_assigned < init_size:
                # Send a (m,) array query to worker
                comm.send(init_query[init_assigned, :], dest=source, tag=SEND_WORKER)
                init_assigned += 1

            else:
                print "MASTER: No more intial work available. Give random work."
                comm.send(domain[random.choice(range(domain.shape[0])), :], 
                          dest=source, tag=SEND_WORKER)

        if tag == WORKER_DONE:
            # data is a (1, m) array
            if dataset == None: 
                dataset = data

            else:
                dataset = np.concatenate((dataset, data), axis=0)

            if contains_row(data[0, :-1], init_query):
                init_done += 1

            string1 = "MASTER: Number of total tasks: %3d. " % init_done
            string2 = "New data from WORKER %2d is: " % source
            print string1 + string2 + str(data)

    print "Complete initial dataset acquired"
    print dataset

    # NN-LR based query system
    optimizer = op.Optimizer(dataset, domain)
    optimizer.train()

    # Select a series of points to query
    selected_points = optimizer.select_multiple(selection_size) # (#points, m) array
    print "Selection size is: " + str(selection_size)

    # Set counters
    listen_to_trainer = True
    trainer_is_ready = True     # Determines if trainer will be used
    trainer_index = 0   # Keeps track of data that trainer doesn't have
    selection_index = 0         # Keeps track of unqueried selected_points 
    queries_done = 0            # Keeps track of total queries done
    queries_total = additional_query_size

    t0 = time.time()

    while closed_workers < num_workers:
        if selection_index == selection_size:
            # Update optimizer's dataset and retrain LR
            optimizer.retrain_LR()                            
            selected_points = optimizer.select_multiple(selection_size) # Select new points
            selection_size = selected_points.shape[0]     # Get number of selected points
            selection_index = 0                           # Restart index
            
        if queries_done < queries_total and trainer_is_ready and (dataset.shape[0] - trainer_index - 1) >= 100:
            # Trainer ready and enough new data for trainer to train a new NN.
            print "MASTER: Trainer has been summoned"
            comm.send(dataset[trainer_index: -1, :], dest=TRAINER, tag=SEND_TRAINER)
            trainer_index = dataset.shape[0] - 1
            trainer_is_ready = not trainer_is_ready # Trainer is not longer available.

        if queries_done >= queries_total and trainer_is_ready:
            print "MASTER: Killing Trainer"
            comm.send("MASTER has fired Trainer", dest=TRAINER, tag=EXIT_TRAINER)

        # Check for data from either worker or trainer
        data = comm.recv(source=MPI.ANY_SOURCE, tag=MPI.ANY_TAG, status=status)
        source = status.Get_source() 
        tag = status.Get_tag()         

        if tag == WORKER_READY:
            if queries_done < queries_total:
                print "MASTER: Sending work to Worker %2d" % source
                comm.send(selected_points[selection_index, :], 
                          dest=source, tag=SEND_WORKER) 
                selection_index += 1

            else:
                print "MASTER: Killing Worker %2d" % source
                comm.send(None, dest=source, tag=EXIT_WORKER)

        elif tag == WORKER_DONE:
            dataset = np.concatenate((dataset, data), axis=0) # data is (m, 1) array
            optimizer.update_data(data)                       # add data to optimizer
            queries_done += 1                                 

            string1 = "MASTER: Number of total tasks: %3d. " % queries_done
            string2 = "New data from WORKER %2d is: " % source
            print string1 + string2 + str(data)

            if queries_done <= queries_total:
                info = "%.3f," % (time.time()-t0)
                f.write(info)

        elif tag == TRAINER_DONE:
            if listen_to_trainer:
                print "MASTER: Updating neural network"
                W, B, architecture = data
                optimizer.update_params(W, B, architecture)

            trainer_is_ready = not trainer_is_ready 

        elif tag == EXIT_WORKER or tag == EXIT_TRAINER:
            closed_workers += 1 

    f.write("NA\n")
    f.close()
    t2 = time.time()
    print "MASTER: Total update time is: %3.3f" % (t2-t1)
    print "Best evaluated point is:"
    print dataset[np.argmax(dataset[:, -1]), :]
    print "MASTER: Predicted best point is:"
    optimizer.retrain_LR()
    domain, pred, hi_ci, lo_ci, nn_pred, ei, gamma = optimizer.get_prediction()
    index = np.argmax(pred[:, 0])
    print np.concatenate((np.atleast_2d(domain[index, :]), np.atleast_2d(pred[index, 0])), axis=1)[0, :]


    # # Plot results
    # if plot_it:
    #     plt.gcf().set_size_inches(8, 8)
    #     true_func = [true_evaluate(domain[i, :], lim_domain)[0, :].tolist() for i in range(domain.shape[0])]
    #     true_func = np.array(true_func)
    #     # optimizer.train()
    #     selected_point = optimizer.select_multiple()[0, :]
    #     print "MASTER: Final selection: " + str(selected_point)
    
    #     domain, pred, hi_ci, lo_ci, nn_pred, ei, gamma = optimizer.get_prediction()
    #     ax = plt.gca()
    #     plt.plot(true_func[:, :-1], true_func[:, -1:], 'k', 
    #              label='True Function',
    #              linewidth=3)
    #     plt.plot(domain, pred, 'c', label='NN-LR Regression', linewidth=3)
    #     # plt.plot(domain, nn_pred, 'r--', label='NN regression', linewidth=7)
    #     plt.plot(domain, hi_ci, 'g--', label='Confidence Interval')
    #     plt.plot(domain, lo_ci, 'g--')
    #     # plt.plot(domain, ei, 'b--', label='ei')
    #     # plt.plot(domain, gamma, 'r', label='gamma')
    #     # plt.plot([selected_point, selected_point], [ax.axis()[2], ax.axis()[3]], 'r--',
    #     #          label='EI selection')
    #     plt.plot(dataset[:,:-1], dataset[:, -1:], 'rv', markersize=7.)
    #     plt.xlabel('Hyperparameter Domain')
    #     plt.ylabel('Objective Function')
    #     plt.title("Neural Network Regression")
    #     plt.legend()
    #     time_index = str(int(time.time()))
    #     figpath = 'figures/mpi_regression_' + time_index + '.eps'
    #     plt.savefig(figpath, format='eps', dpi=2000)
    #     # plt.show()

    #     plt.clf()
    #     plt.gcf().set_size_inches(8, 8)
    #     plt.plot(domain, ei, 'r', label='Expected Improvement')
    #     plt.plot(domain, ((hi_ci-pred)/2)**2, 'g', label='Variance')
    #     plt.xlabel('Hyperparameter Domain')
    #     plt.ylabel('Expected Improvement')
    #     plt.title("Selection Criteria")
    #     plt.legend()
    #     figpath = 'figures/mpi_expected_improvement_' + time_index + '.eps'
    #     plt.savefig(figpath, format='eps', dpi=2000)
        


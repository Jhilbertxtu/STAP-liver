"""
This script reads pre-segmented liver data, assembles a dataset,
extracts features, trains a SVM on the data and reports training
quality. The SVM model built is stored in the "./models" folder.

Author: 
 * Mateus Riva (mriva@ime.usp.br)
"""
import sys
from itertools import chain
from time import time
import numpy as np
import optparse
import random

from sklearn.model_selection import GridSearchCV
from sklearn.metrics import precision_recall_fscore_support, classification_report, confusion_matrix
from sklearn.decomposition import PCA
from sklearn.svm import SVC

import lss_data, lss_features, lss_util
printv = lss_util.printv
printvv = lss_util.printvv


################################################################
# Reading and parsing command-line arguments
parser = optparse.OptionParser("usage: %prog [options] data_folder [data_folder2 ...]")

#parser.add_option("-d", "--data-folder", dest="data_folder",
#               default="error", type="string",
#               help="folder containing liver segmentation data (subfolders will be checked).")
parser.add_option("-w", "--window-size", dest="window_code", default="553",
               type="string", help="window size string: 'xyz'. Example: '553' uses a 5x5x3 window.")
parser.add_option("-f", "--features", dest="features_string", default="coordinates,intensity",
               type="string", help="features to be extracted from the data. Example: 'coordinates,intensity'. Don't use spaces, split by commas. Further information available at the README [TODO]")
parser.add_option("-c", "--components", dest="pca_components_total", default=20,
               type="int", help="number of PCA components to be extracted.")
parser.add_option("-e", "--epochs", dest="max_epochs", default=100,
               type="int", help="maximum number of training epochs.")
parser.add_option("-t", "--threshold", dest="convergence_threshold", default=0.95,
               type="float", help="threshold for convergence. Training stops if max epochs reached or if precision and recall of both classes exceed threshold.")
parser.add_option("-i", "--initial-size", dest="initial_train_size", default=1000,
               type="int", help="size of the initial (balanced) train set.")
parser.add_option("-l", "--learning-rate", dest="learning_rate", default=0.1,
               type="float", help="learning rate (percentage of hard samples added to train set per epoch).")
parser.add_option("-m", "--model-filename", dest="model_filename", default='out.pkl',
               type="string", help="filename for storage of final model.")
parser.add_option("-v", "--verbose", action="store_true", dest="verbose", default=False)
parser.add_option("-V", "--very-verbose", action="store_true", dest="very_verbose", default=False)

(options, args) = parser.parse_args()

#Mandatory arguments
if len(args) < 1:
    print("Error: no data folder(s) specified.")
    parser.print_usage()
    sys.exit(2)
data_folders = args
window_code = options.window_code
window_size = (int(window_code[0]), int(window_code[1]), int(window_code[2])) # converting window string code to int tuple
features_string = options.features_string
pca_components_total = options.pca_components_total
max_epochs = options.max_epochs
convergence_threshold = options.convergence_threshold
initial_train_size = options.initial_train_size
learning_rate = options.learning_rate
model_filename = options.model_filename
lss_util.verbose = options.verbose
lss_util.very_verbose = options.very_verbose

################################################################
# Reading supervised liver data
t0 = time()
printv("Loading data from {}... ".format(data_folders), end="", flush=True)

raw_dataset = list(chain.from_iterable([lss_data.load_folder(data_folder) for data_folder in data_folders]))

#TODO: make this dynamic
classes_count, target_names = 2, ['0','1']

printv("Done in {:.3f}s. Loaded {} patients.".format(time()-t0, len(raw_dataset)))

################################################################
# Assembling dataset of patches
t0 = time()
printv("Dividing dataset into patches of size {}... ".format(window_size), end="", flush=True)

patch_dataset, patch_stats = lss_data.patch_dataset(raw_dataset, window_size)

printv("Done in {:.3f}s.".format(time()-t0))

# Print stats on dataset
print("Total of patches: {}".format(patch_stats['total']))
print("Non-target patches: {} ({:.2f}%)".format(patch_stats['per_class'][0], (patch_stats['per_class'][0]*100/patch_stats['total'])))
print("    Target patches: {} ({:.2f}%)".format(patch_stats['per_class'][1], (patch_stats['per_class'][1]*100/patch_stats['total'])))

################################################################
# Extracting features
t0 = time()
printv("Extracting features {}... ".format(features_string), end="", flush=True)

feature_dataset, feature_count = lss_features.extract_features(patch_dataset, features_string)

printv("Done in {:.3f}s. {} features extracted.".format(time()-t0, feature_count))

################################################################
# Assembling training and test sets
t0 = time()
printv("Assembling full test set... ", end="", flush=True)

# Initializing full X set as an empty numpy array of shape (examples, features)
X = np.empty((len(feature_dataset), feature_count))
# Copying feature dataset to X
for i, element in enumerate(feature_dataset):
    X[i,:] = element['features']

# Initializing full y set as an empty numpy array of shape (examples)
y = np.empty((len(feature_dataset)))
# Copying feature dataset to y
for i, element in enumerate(feature_dataset):
    y[i] = element['target']

printv("Done in {:.3f}s. 'X' has shape {}; 'y' has shape {}.".format(time()-t0, X.shape, y.shape))

# Referencing variables for ease of understanding
X_test, y_test = X, y

# Assembling the training set
t0 = time()
printv("Assembling training set... ", end="", flush=True)

# Initializing train set as numpy arrays
X_train, y_train = lss_data.assemble_initial_train_set(X, y, initial_train_size)

printv("Done in {:.3f}s. 'X_train' has shape {}; 'y_train' has shape {}.".format(time()-t0, X_train.shape, y_train.shape))

# Computing PCA for full dataset
# TODO: PCA over whole dataset optional?
t0 = time()
printv("Computing PCA with {} components... ".format(pca_components_total), end="", flush=True)

pca = PCA(n_components=pca_components_total, svd_solver='randomized', whiten=True).fit(X)

printv("Done in {:.3f}s.".format(time()-t0))

################################################################
# Training the SVM

# Hard sample loop: train until convergence or max epochs reached
converged = False
current_epoch = 0
while (current_epoch < max_epochs and not converged):
    print("On epoch {}. Training set has size {} (per class: {}), testing set has size {} (per class: {})".format(current_epoch, len(X_train), list(np.unique(y_train, return_counts=True)[1]), len(X_test), list(np.unique(y_test, return_counts=True)[1])))

    # transforming Xs using PCA
    t0 = time()
    printv("Projecting X into PCA... ", end="", flush=True)
    
    X_train_pca = pca.transform(X_train)
    X_test_pca = pca.transform(X_test)
    
    printv("Done in {:.3f}s.".format(time()-t0))

    # fitting the classifier, using a grid search
    t0 = time()
    printv("Fitting the classifier to the training set... ", end="", flush=True)

    #param_grid = {'C': [1e3, 5e3, 1e4, 5e4, 1e5],
    #              'gamma': [0.0001, 0.0005, 0.001, 0.005, 0.01, 0.1], }
    param_grid = {'C': [1e3],
                'gamma': [0.1], }
    clf = GridSearchCV(SVC(kernel='rbf', class_weight='balanced'), param_grid)
    clf = clf.fit(X_train_pca, y_train)

    printv("Done in {:.3f}s. Best parameters: C: {}, gamma: {}".format(time()-t0, clf.best_estimator_.C, clf.best_estimator_.gamma))

    # Testing the model on the test set
    t0 = time()
    printv("Predicting bg/fg patches in the test set... ", end="", flush=True)
    
    y_pred = clf.predict(X_test_pca)
    
    printv("Done in {:.3f}s.".format(time()-t0))

    # Computing results and assessing convergence
    precision, recall, f_score, support = precision_recall_fscore_support(y_test, y_pred)
    print(classification_report(y_test, y_pred, target_names=target_names))
    print(confusion_matrix(y_test, y_pred, labels=range(classes_count)))
    # Check if the precision and recall of every class is above the convergence threshold
    if all(np.array(precision) > convergence_threshold) and all (np.array(recall) > convergence_threshold):
        convergence = True
        break

    # Selecting hard samples
    hard_samples_indexes = [idx for idx, targets in enumerate(zip(y_test, y_pred)) if targets[0] != targets[1]]
    hard_samples_chosen = random.sample(hard_samples_indexes, int(learning_rate*len(hard_samples_indexes)))

    print("Picked {} hard samples out of {}".format(len(hard_samples_chosen), len(hard_samples_indexes)))

    # Adding hard samples to train
    X_hard_samples = X_test[hard_samples_chosen]
    y_hard_samples = y_test[hard_samples_chosen]

    X_train = np.concatenate((X_train, X_hard_samples))
    y_train = np.concatenate((y_train, y_hard_samples))

    # Update epoch count
    print("End of epoch {} ------------------\n".format(current_epoch))
    current_epoch += 1

################################################################
# Final report and model storing
print("Training complete. Total of epochs: {}".format(current_epoch))

# Testing on full dataset
# transforming Xs using PCA
t0 = time()
printv("Projecting X into PCA... ", end="", flush=True)

X_pca = pca.transform(X)

printv("Done in {:.3f}s.".format(time()-t0))

# Testing the model on the test set
t0 = time()
printv("Predicting bg/fg patches in the test set... ", end="", flush=True)

y_pred = clf.predict(X_pca)

printv("Done in {:.3f}s.".format(time()-t0))

# Computing results
print(classification_report(y_test, y_pred, target_names=target_names))
print(confusion_matrix(y_test, y_pred, labels=range(classes_count)))

# Store model
from sklearn.externals import joblib
joblib.dump(clf, '{}'.format(model_filename)) 
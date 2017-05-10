# -*- coding: utf-8 -*-
"""
Created on Wed Mar 22 15:48:23 2017

@author: Chris Tasich
"""
#==============================================================================
# IMPORT PACKAGES
#==============================================================================

import numpy as np
import pandas as pd
import squarify as sq
# from scipy import ndimage


#==============================================================================
# LOAD TIDES
#==============================================================================

def load_tides(file,parser,start,end):
    df = pd.read_csv(file,parse_dates=['datetime'],date_parser=parser,index_col='datetime')
    df1 = df[(df.index >= start) & (df.index < end) & (df.index.minute == 0)]
    df2 = df1['pressure'] - np.mean(df1['pressure'])
    return df2

#==============================================================================
# CHANGE IN ELEVATION
#==============================================================================

def delta_z(heads,time,ws,rho,SSC,dP,dO,z0):
    C0 = np.zeros(len(heads))
    C = np.zeros(len(heads))
    dz = np.zeros(len(heads))
    dh = np.zeros(len(heads))
    z = np.zeros(len(heads)+1)
    z[0:2] = z0
    dt = float((time[1]-time[0]).seconds)
    j = 1
    for h in heads[1:]:
        dh[j] = (h-heads[j-1])/dt
        C0[j] = 0
        if h > z[j]:
            if dh[j] > 0:
                C0[j] = 0.69*SSC*(h-z[j])
                C[j] = (C0[j]*(h-heads[j-1])+C[j-1]*(h-z[j]))/(2*h-heads[j-1]-z[j]+ws/dt)
            else:
                C[j] = (C[j-1]*(h-z[j]))/(h-z[j]+ws/dt)
        else:
            C[j] = 0
        dz[j] = (ws*C[j]/rho)*dt
        z[j+1] = z[j] + dz[j] + dO - dP
        j = j + 1
    z = z[-1]
    return (z)

#==============================================================================
# CALCULATE WATER LOGGING RISK
#==============================================================================

# Logit Function
def logit(z,k,mid):
    x = 1.0 / (1.0 + np.exp(-k*(z-mid)))
    return x

#==============================================================================
# EXTRACT A RECTANGULAR SECTION THROUGH A CUBE AND COLLAPSE
#==============================================================================

# Given a cube dc[z,y,x], extract a rectangula prism in (x,y), that extends
# through all z-values, then ravel the x and y dimensions to produce a
# 2D array with rows = z and columns = raveled x,y.

def extract_and_collapse(dc, p):
    x = dc[:,p[2]:p[3],p[0]:p[1]]
    x = x.reshape((x.shape[0], x.shape[1] * x.shape[2]))
    return x

#==============================================================================
# DEFINE CLASSES
#==============================================================================

class household(object):
    def __init__(self, id, wealth = 0, plots = None, discount = 0.03):
        self.id = id
        self.wealth = wealth
        self.discount = discount
        if plots is None:
            self.plots = np.zeros((0,5), dtype=np.integer)
        else:
            self.plots = np.array(plots, dtype=np.integer)

    def utility(self, profit_dc):
        own_patches_profit = np.concatenate([ extract_and_collapse(profit_dc, p) for p in self.plots ],
                                      axis = 0)
        profit = np.sum(own_patches_profit, axis = 0)
        eu = self.wealth + np.sum(profit * np.exp(- self.discount * np.arange(len(profit))))
        return eu

class polder(object):
    def __init__(self, x, y, border_height = 3.0,
                 n_households = 0, max_wealth = 1.0E4,
                 gini = 0.3):
        self.width = x
        self.height = y
        self.border_height = border_height
        self.max_wealth = max_wealth
        self.plots = np.zeros(shape = (0,5), dtype = np.integer)
        self.initialize_elevation()
        self.initialize_hh(n_households)

    def initialize_elevation(self):
        wx = np.pi / self.width
        wy = np.pi / self.height
        self.elevation = self.border_height * \
            ( \
             (1.0 - \
               np.outer(np.sin(np.arange(self.height) * wy),
                        np.sin(np.arange(self.width)) * wx)) + \
              np.random.normal(0.0, 0.1, (self.height, self.width)) \
            )
        self.elevation_cube = np.reshape(self.elevation, (1, self.height, self.width))

    def set_elevation(self, elevation, plots, n_households = None):
        if n_households is None:
            n_households = len(self.households)
        self.elevation = elevation
        self.owners = np.zeros_like(self.elevation, dtype = np.integer)
        self.plots = plots
        self.initialize_hh_from_plots(n_households)
        self.elevation_cube = np.reshape(self.elevation, (self.height, self.width, 1))

    def initialize_hh(self, n_households):
        self.owners = np.zeros_like(self.elevation, dtype = np.integer)
        self.households = []
        if n_households > 0:
            self.build_households(n_households)
            for hh in self.households:
                for p in hh.plots:
                    self.owners[p[2]:p[3],p[0]:p[1]] = hh.id

    def initialize_hh_from_plots(self, n_households):
        assert max(self.owners) < n_households
        self.households = [household(id = i) for i in range(n_households)]
        self.set_hh_plots()

    def set_households(self, households):
        self.households = households
        self.owners = np.zeros_like(self.elevation, dtype = np.integer)
        self.set_owners_wealth()

    def set_hh_wealth(self, hh):
        z = self.elevation[self.owners == hh.id]
        if z.size == 0:
            hh.wealth = 0
        else:
            hh.wealth = self.max_wealth * z.size * z.mean() / self.border_height

    def set_owners_wealth(self):
        for hh in self.households:
            for p in hh.plots:
                self.owners[p[2]:p[3],p[0]:p[1]] = hh.id
            self.set_hh_wealth(hh)

    def set_hh_plots(self):
        for hh in self.households:
            plots = self.plots[self.plots[:,4] == hh.id]
            hh.plots = plots
        self.set_owners_wealth()

    def build_plots(self, weights):
        plot_sizes = sq.normalize_sizes(weights, self.width, self.height)
        plots = sq.squarify(plot_sizes, 0, 0, self.width, self.height)
        plots = pd.DataFrame(plots, columns = ('x', 'y', 'dx', 'dy'))
        plots['xf'] = plots['x'] + plots['dx']
        plots['yf'] = plots['y'] + plots['dy']
        plots = plots[['x','xf','y','yf']]
        plots = np.array(np.round(plots), dtype = np.integer)
        plots = np.concatenate((plots,
                               np.expand_dims(np.arange(plots.shape[0], dtype=np.integer),
                                              axis = 1)),
                               axis = 1)
        self.plots = plots

    def build_households(self, n = None, gini = 0.3):
        if n is not None and n != len(self.households):
            print "Initializing", n, "households"
            self.households = [household(id = i) for i in range(n)]
        else:
            print "n = ", type(n), ", ", n, ", length = ", len(self.households)
        if isinstance(gini, dict):
            gini_land = gini['land']
        elif isinstance(gini, (list,tuple)):
            if (len(gini) > 1):
                gini_land = gini[0]
            else:
                gini_land = gini[0]
        else:
            gini_land = gini

        alpha = (1.0 / gini_land + 1.0) / 2.0
        weights = np.random.pareto(alpha, size = len(self.households))

        self.build_plots(weights)
        self.set_hh_plots()

    def calc_profit(self, water_level, max_profit, k):
        self.profit = logit(self.elevation_cube, k, water_level / 2.0)

    def calc_eu(self):
        eu = [hh.utility(self.profit) for hh in self.households]
        return eu


pdr = polder(x = 200, y = 100, n_households = 50)




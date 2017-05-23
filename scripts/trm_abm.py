# -*- coding: utf-8 -*-
"""
Created on Wed Mar 22 15:48:23 2017

@author: Chris Tasich
"""
#==============================================================================
# IMPORT PACKAGES
#==============================================================================

import numpy as np
import numpy.ma as ma
import pandas as pd
import squarify as sq
from scipy.signal import argrelextrema
import time
import matplotlib.pyplot as plt
# import pdb
# from itertools import izip, count
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

def  aggrade_patches(heads,times,ws,rho,SSC,dP,dO,z0, z_breach):
    z = z0.copy()
    C_last = np.zeros_like(z0)
    dt = float((times[1]-times[0]).seconds)
    delta_h = (heads.values[1:] - heads.values[:-1])
    for h, dh in zip(heads[1:], delta_h):
        if h > z_breach:
            delta_z = ma.masked_less_equal(h-z, 0.0)
            delta_z.set_fill_value(0.0)
            if dh > 0:
                # C0 = 0.69 * SSC * delta_z
                C_next = ( delta_z * ( 0.69 * dh * SSC + C_last) ) / (delta_z + dh + ws/dt)
            else:
                C_next = ( C_last * delta_z ) / (delta_z + ws/dt)
        else:
            C_next = ma.array(np.zeros_like(z0), ma.nomask)
        C_last = C_next.filled()
        dz = C_last * ws * dt / rho
        z += dz + dO - dP
        # print "Sum(dz) = ", np.sum(dz), ", Sum(C_last) = ", np.sum(C_last)
    return (z)

#==============================================================================
# CALCULATE WATER LOGGING RISK
#==============================================================================

# Logit Function
def logit(z,k,mid):
    x = 1.0 / (1.0 + np.exp(-k*(z-mid)))
    return x

#==============================================================================
# DEFINE CLASSES
#==============================================================================

class election(object):
    def __init__(self, hh_dict):
        self.households = hh_dict

    def utility(self, index):
        u = dict( [ (hh.id, hh.eu_df.eu.loc[index]) for hh in self.households.values() ] )
        return(u)

    def count_unhappy(self, index):
        utilities = self.utility(index)
        baseline = dict( [ (hh.id, hh.eu_df.eu.iloc[0]) for hh in self.households.values() ] )
        n = sum([ baseline[hh_id] > utilities[hh.id] for hh_id in utilities.keys() ])
        return n

    def vote(self):
        ballots = np.array( [ np.array(hh.vote(), dtype = np.integer) \
                  for hh in self.households.values() ] )
        winner = election.instant_runoff(ballots)
        return (winner, self.utility(winner))

    @staticmethod
    def instant_runoff(ballots):
        majority = ballots.shape[0] * 0.5
        n_choices = ballots.shape[1]
        ballots = pd.DataFrame(ballots)
        vc = ballots[0].value_counts()
        while vc.iloc[0] <= majority:
            vc = ballots[n_choices - 1].value_counts()
            eliminate = vc.index[0]
            blist = [ list(x) for x in list(np.array(ballots)) ]
            for b in blist: b.remove(eliminate)
            ballots = pd.DataFrame(np.array(blist, dtype = np.integer))
            n_choices = ballots.shape[1]
            vc = ballots[0].value_counts()
        return vc.index[0]

class transaction(object):
    def __init__(self, buyer, seller, year, price):
        self.buyer = buyer
        self.seller = seller
        self.year = year
        self.price = price

    def buyer_id(self):
        return self.buyer.id

    def seller_id(self):
        return self.seller.id

class auction(object):
    def __init__(self, hh_dict):
        self.households = hh_dict
        self.transactions = []
        self.ballots = None
        self.initialize_votes()

    def utility(self, index):
        u = dict( [ (hh.id, hh.eu_df.eu.loc[index]) for hh in self.households.values() ] )
        trans = [t for t in self.transactions if t.year == index]
        for t in trans:
            u[t.buyer_id()] -= t.price
            u[t.seller_id()] += t.price
        return(u)

    def count_unhappy(self, index):
        utilities = self.utility(index)
        baseline = dict( [ (hh.id, hh.eu_df.eu.iloc[0]) for hh in self.households.values() ] )
        n = sum([ baseline[hh_id] > utilities[hh.id] for hh_id in utilities.keys() ])
        return n

    def vote(self, force = False):
        if self.ballots is None:
            return None
        majority = 0.5 * self.ballots.shape[0]
        votes = pd.DataFrame(self.ballots)[0].value_counts()
        print(votes)
        if votes.iloc[0] > majority:
            return votes.index[0]
        elif force:
            return votes.index[0]
        return None

    def initialize_votes(self):
        self.ballots = np.array( [ hh.vote() for hh in self.households.values() ] )
        self.transactions = []

    def auction(self, max_rounds = 1000):
        global tt, bbids
        self.initialize_votes()
        for round in range(max_rounds):
            print "Round ", round
            winner = self.vote()
            if winner is not None:
                return (winner, self.utility(winner))
            target = self.vote(force = True)
            print "Target = ", target
            buyers  = [trans.buyer for trans in self.transactions]
            sellers = [trans.seller for trans in self.transactions]
            buyer_ids = [ b.id for b in buyers ]
            seller_ids = [ s.id for s in sellers ]
            neutral_ids = list(set(self.households.keys()) - set(buyer_ids) - set(seller_ids))
            neutral = [ self.households[hh_id] for hh_id in neutral_ids ]
            for hh in neutral:
                hh.construct_bids(target)
            for hh in buyers:
                purchases = [ t for t in self.transactions if t.buyer_id() == hh.id ]
                hh.construct_bids(target, purchases)
            bids = pd.concat([hh.bids for hh in neutral + buyers])
            bbids = bids.copy()
            transactions = self.bidding_round(bids)
            tt = transactions
            for trans in transactions:
                trans.buyer.wealth -= trans.price
                trans.seller.wealth += trans.price
                self.ballots[trans.seller_id()] = trans.year
            if len(transactions) > 0:
                print len(transactions), " Transactions"
                self.transactions += transactions
            else:
                print "No transactions"
                break
        winner = self.vote(force = True)
        return (winner, self.utility(winner))

    def bidding_round(self,bids):
        global pp, wtpp, wtaa, p0, bcc, scc
        transactions = []
        wta = bids[np.logical_not(bids.is_offer.values)][['id', 'year','amount']]
        wtp = bids[bids.is_offer.values][['id', 'year','amount']]
        wtpp = wtp.copy()
        wtaa = wta.copy()
        # wta = wta.drop_duplicates(inplace = True)
        # wtp = wtp.drop_duplicates(inplace = True)
        if wta is None or wta.shape[0] < 2:
            print "Empty wta"
            return transactions
        if wtp is None or wtp.shape[0] < 2:
            print "Empty wtp"
            return transactions
        wta = wta.pivot(index = 'id', columns = 'year', values = 'amount')
        wtp = wtp.pivot(index = 'id', columns = 'year', values = 'amount')
        wtpp = wtp.copy()
        wtaa = wta.copy()
        wta_min = wta.min()
        wtp_max = wtp.max()
        for buyer_index in np.random.choice(wtp.index, wtp.shape[0], replace = False):
            buyer = wtp.loc[buyer_index]
            buyer_year = buyer[np.logical_not(buyer.isnull())]
            offer = buyer_year.values[0]
            seller_candidates = wta[buyer_year.index]
            seller_candidates = seller_candidates[np.logical_not(pd.isnull(seller_candidates.values))]
            seller_candidates = seller_candidates[seller_candidates.values <= offer]
            if seller_candidates.shape[0] > 0:
                print "Year ", buyer_year.index[0], ": ", buyer.index[0], " offers ", offer
                print "     seller_candidates has shape ", seller_candidates.shape
                seller_index = np.random.choice(seller_candidates.index, 1)[0]
                seller = seller_candidates.loc[seller_index]
                accept = seller.values[0]
                print "Year ", buyer_year.index[0], ": ", buyer.index[0], " offers ", offer, " and ", \
                    seller.index[0], " will accept ", accept
                if  offer >= accept:
                    price = (offer + accept) / 2.0
                    print "Offer accepted: price = ", price
                    if True: # self.households[p.buyer].wealth >= price:
                        print buyer_index, seller_index
                        bh = self.households[buyer_index]
                        sh = self.households[seller_index]
                        tx = transaction(bh, sh, buyer_year.index, price)
                        transactions.append(tx)
                        wtp.drop(buyer_index, inplace = True)
                        wta.drop(seller_index, inplace = True)
                else:
                    print "Offer rejected."
            if wta.shape[0] == 0 or wtp.shape[0] == 0:
                break
        print len(transactions), " transactions."
        return transactions

class household(object):
    def __init__(self, id, wealth = 0, plots = None, discount = 0.03, eu_df = None):
        self.id = id
        self.wealth = wealth
        self.discount = discount
        self.eu_df = eu_df
        self.bids = pd.DataFrame(index = [], columns = ['id', 'year', 'is_offer', 'amount'])
        if plots is None:
            self.plots = np.zeros((0,5), dtype=np.integer)
        else:
            self.plots = np.array(plots, dtype=np.integer)

    def utility(self, profit_dc):
        own_patches_profit = np.concatenate([ household.extract_and_collapse(profit_dc, p) \
                                             for p in self.plots ],
                                      axis = 0)
        profit = np.sum(own_patches_profit, axis = 0)
        eu = np.sum(profit * np.exp(- self.discount * np.arange(len(profit))))
        return eu

    def set_eu(self, eu_df):
        self.eu_df = eu_df.sort_values('eu', ascending = False)

    def construct_bids(self, target, purchases = []):
        bid_scale = 1.1
        assert(self.eu_df is not None)
        favorite = self.eu_df.iloc[0]
        others = self.eu_df.iloc[1:]
        # print "Target = ", target
        if target == favorite.year:
            target = self.eu_df.index[1]
        target_eu = self.eu_df.eu.loc[target]


        sell_bids = pd.DataFrame({ \
                  'id': self.id,
                  'year':others.year,
                  'is_offer':False,
                  'amount':(favorite.eu - others.eu) * np.random.uniform(1.0, bid_scale),
                  })
        buy_bids = pd.DataFrame({ \
                  'id': (self.id,),
                  'year': (self.eu_df.index[0],),
                  'is_offer': (True,),
                  'amount':((favorite.eu - target_eu) / np.random.uniform(1.0, bid_scale),)\
                  })
        if False:
            buy_bids.amount = buy_bids.amount.clip(None, self.wealth)
        if (len(purchases) > 0):
            self.bids = buy_bids[ buy_bids.year == purchases[0].year]
        else:
            self.bids = pd.concat([buy_bids, sell_bids])
        self.bids = self.bids[self.bids.amount > 0.0]

    def vote(self):
        return self.eu_df.year.copy()

    #==========================================================================
    # EXTRACT A RECTANGULAR SECTION THROUGH A CUBE AND COLLAPSE
    #==========================================================================

    # Given a cube dc[z,y,x], extract a rectangula prism in (x,y), that extends
    # through all z-values, then ravel the x and y dimensions to produce a
    # 2D array with rows = z and columns = raveled x,y.

    @staticmethod
    def extract_and_collapse(dc, p):
        x = dc[:,p[1]:(p[1] + p[3]),p[0]:(p[0] + p[2])].copy()
        x = x.reshape((x.shape[0], x.shape[1] * x.shape[2]))
        return x

class breach(object):
    def __init__(self, pldr, breach_x, breach_y, breach_z):
        self.pldr = pldr
        self.x = breach_x
        self.y = breach_y
        self.z_breach = breach_z
        xx,yy = np.meshgrid(np.arange(pldr.width), np.arange(pldr.height))
        delta_x = xx - breach_x
        delta_y = yy - breach_y
        self.dist = np.hypot(delta_x, delta_y)
        self.scaled_dist = self.dist / 1000. + 1.
        self.A = 0.0


class polder(object):
    def __init__(self, x, y,
                 time_horizon,
                 n_households = 0,
                 max_wealth = 1.0E4, max_profit = 100.,
                 gini = 0.3,
                 border_height = 1.0,
                 amplitude = 1.5,
                 noise = 0.05):
        self.width = x
        self.height = y
        self.border_height = border_height
        self.max_wealth = max_wealth
        self.max_profit = max_profit
        self.time_horizon = time_horizon
        self.breach_duration = 0
        self.current_period = 0
        self.plots = np.zeros(shape = (0,5), dtype = np.integer)
        self.breaches = []
        self.initialize_elevation(border_height = border_height,
                                  amplitude = amplitude, noise = noise)
        self.initialize_hh(n_households)

    def initialize_elevation(self, border_height = None, amplitude = 1.0, noise = 0.05):
        if border_height is None:
            border_height = self.border_height
        wx = np.pi / self.width
        wy = np.pi / self.height
        self.elevation = border_height - amplitude * \
              np.outer(np.sin(np.arange(self.height) * wy),
                        np.sin(np.arange(self.width) * wx)) + \
              noise * np.random.normal(0.0, 1.0, (self.height, self.width))
        self.elevation_cube = np.zeros((self.time_horizon + 1, self.height, self.width))
        self.elevation_cube[0] = self.elevation
        self.current_period = 0

    def set_elevation(self, elevation, plots, n_households = None):
        if n_households is None:
            n_households = len(self.households)
        self.elevation = elevation
        self.owners = np.zeros_like(self.elevation, dtype = np.integer)
        self.plots = plots
        self.initialize_hh_from_plots(n_households)
        self.elevation_cube = np.zeros((self.time_horizon + 1, self.height, self.width))
        self.elevation_cube[0] = self.elevation
        self.current_period = 0

    def initialize_hh(self, n_households):
        self.owners = np.zeros_like(self.elevation, dtype = np.integer)
        self.households = dict()
        if n_households > 0:
            self.build_households(n_households)
            self.owners.fill(-1)
            for hh in self.households.values():
                for p in hh.plots:
                    self.owners[p[1]:(p[1]+p[3]),p[0]:(p[0]+p[2])] = hh.id

    def initialize_hh_from_plots(self, n_households):
        assert max(self.owners) < n_households
        self.households = dict([(i, household(id = i)) for i in range(n_households)])
        self.set_hh_plots()

    def set_households(self, households):
        if isinstance(households, dict):
            self.households = households
        else:
            # list of households
            self.households = dict((hh.id, hh) for hh in households)
        self.owners = np.zeros_like(self.elevation, dtype = np.integer)
        self.set_owners_wealth()

    def set_hh_wealth(self, hh):
        z0 = self.elevation.min() - 0.5
        z = self.elevation[self.owners == hh.id]
        if z.size == 0:
            hh.wealth = 0
        else:
            hh.wealth = self.max_wealth * np.sqrt(z.size) * (z.mean() - z0) / (self.border_height - z0)

    def set_owners_wealth(self):
        self.owners.fill(-1.0)
        for hh in self.households.values():
            for p in hh.plots:
                self.owners[p[1]:(p[1]+p[3]),p[0]:(p[0]+p[2])] = hh.id
            self.set_hh_wealth(hh)

    def set_hh_plots(self):
        for hh in self.households.values():
            hh.plots = []
        for i in range(self.plots.shape[0]):
            hh = self.households[self.plots[i,4]]
            hh.plots.append(self.plots[i,:4])
        self.set_owners_wealth()

    @staticmethod
    def build_subplots(weights, x0, y0, dx, dy, ix0 = 0):
        plot_sizes = sq.normalize_sizes(weights, dx, dy)
        plots = sq.squarify(plot_sizes, x0, y0, dx, dy)
        plots = pd.DataFrame(plots, columns = ('x', 'y', 'dx', 'dy'))
        plots['dx'] = np.round(plots['x'] + plots['dx']) - np.round(plots['x'])
        plots['dy'] = np.round(plots['y'] + plots['dy']) - np.round(plots['y'])
        plots = plots[['x','y','dx','dy']]
        plots = np.array(np.round(plots), dtype = np.integer)
        plots = np.concatenate( \
                   ( \
                    plots, \
                    np.expand_dims( np.arange(plots.shape[0], dtype=np.integer),
                                   axis = 1)  + int(ix0) \
                   ), \
                 axis = 1)
        return plots

    def build_plots(self, weights, n_boxes = 10):
        n = weights.size / n_boxes
        remainder = weights.size % n
        w = np.random.choice(weights, weights.size, False)
        wr = w[0:remainder]
        w = w[remainder:]
        w_list = np.random.choice(w, size = (n_boxes, n), replace = False)
        w_list = [ w_list[i] for i in range(w_list.shape[0])]
        if remainder > 0:
            i_dest = np.random.choice(n_boxes, remainder, replace = True)
            for i, j in enumerate(i_dest):
                w_list[j] = np.append(w_list[j], wr[i])
        grid_weights = [ np.sum(x) for x in w_list ]
        scaled_grid_weights = sq.normalize_sizes(grid_weights, self.width, self.height)
        grid = sq.squarify(scaled_grid_weights, 0, 0, self.width, self.height)
        grid = pd.DataFrame(grid, columns = ('x', 'y', 'dx', 'dy'))
        grid['dx'] = np.round(grid['x'] + grid['dx']) - np.round(grid['x'])
        grid['dy'] = np.round(grid['y'] + grid['dy']) - np.round(grid['y'])
        grid = np.array(np.round(grid), dtype = np.integer)
#        self.grid = grid.copy()
#        self.w_list = w_list
#        self.grid_weights = grid_weights

        cum_len = np.cumsum( np.concatenate( (np.zeros((1,)), [len(ww) for ww in w_list[:-1]]) ) )

        plot_list = [ self.build_subplots(w_list[i], \
                          grid[i,0], grid[i,1], grid[i,2], grid[i,3],
                          ix0 = cum_len[i]) \
                      for i in range(len(w_list)) ]
#        self.plot_list = plot_list
        plots = np.concatenate(plot_list, axis = 0)
        self.plots = plots

    def build_households(self, n = None, gini = 0.3):
        if n is not None and n != len(self.households):
            print "Initializing", n, "households"
            self.households = dict([(i, household(id = i)) for i in range(n)])
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

    def calc_profit(self, water_level, k, elevation_cube = None, save = True):
        if elevation_cube is None:
            elevation_cube = self.elevation_cube
        profit = self.max_profit * logit(elevation_cube, k, water_level / 2.0)
        if save:
            self.profit = profit.copy()
        return profit

    def calc_eu(self, profit_cube = None, save = True):
        if profit_cube is None:
            profit_cube = self.profit.copy()
        hh_eu = dict([(hh.id, hh.utility(profit_cube)) for hh in self.households.values()])
        eu = np.zeros_like(self.owners, np.double)
        for i in range(eu.shape[0]):
            for j in range(eu.shape[1]):
                eu[i,j] = hh_eu[self.owners[i,j]]
        if save:
            self.eu = eu.copy()
        return (eu, hh_eu)

    def set_hh_eu(self, ids, eu_array):
        n_years = eu_array.shape[0]
        for i, hh_id in enumerate(ids):
            df = pd.DataFrame({'year':range(n_years), 'eu':eu_array[:,i]})
            self.households[hh_id].set_eu(df)

    def calc_eu_slice(self, trm_water_level, trm_k, wl_water_level, wl_k, ec, horizon, duration):
            ec1 = ec.copy()
            profit = np.zeros_like(ec, np.double)
            for j in range(duration + 1, horizon + 1):
                ec1[j] = ec1[duration]
            profit[:duration] = self.calc_profit(trm_water_level, trm_k, ec1[:duration], False)
            profit[duration:] = self.calc_profit(wl_water_level, wl_k, ec1[duration:], False)
            eu, hh_eu = self.calc_eu(profit, False)
            return(eu, hh_eu)

    def calc_eu_series(self, trm_water_level, trm_k, wl_water_level, wl_k, horizon = None, elevation_cube = None, save = True):
        if horizon is None:
            horizon = self.time_horizon
        if elevation_cube is None:
            elevation_cube = self.elevation_cube
        eu_cube = np.zeros((horizon , self.elevation.shape[0], self.elevation.shape[1]), np.double)
        ec0 = elevation_cube[:horizon+1].copy()
        hh_eu_array = np.zeros((horizon, len(self.households)))
        hh_id_list = self.households.keys()
        for i in range(horizon):
            eu, hh_eu = self.calc_eu_slice(trm_water_level, trm_k, wl_water_level, wl_k, ec0, horizon, i)
            eu_cube[i] = eu.copy()
            hh_eu_array[i] = [hh_eu[hh_id].copy() for hh_id in hh_id_list]
        self.eu_cube = eu_cube.copy()
        self.set_hh_eu(hh_id_list, hh_eu_array)
        return eu_cube

    def add_breach(self, breach_x, breach_y, duration):
        self.breach_duration = duration,
        self.breaches.append(breach(self, breach_x, breach_y, self.border_height))

    def aggrade(self, heads, ws, rho, SSC, dP, dO, period = -1):
        if period < 0:
            period = self.current_period + 1
        assert(period > 0 and period <= self.time_horizon)
        sed_load = np.zeros_like(self.elevation)
        for b in self.breaches:
            sed_load += SSC * b.scaled_dist ** -2.3
        new_layer = self.elevation_cube[period - 1]
        new_layer = aggrade_patches(heads, heads.index, ws, rho, sed_load, dP, dO, new_layer, self.border_height)
        self.elevation_cube[period] = new_layer
        self.current_period = period

